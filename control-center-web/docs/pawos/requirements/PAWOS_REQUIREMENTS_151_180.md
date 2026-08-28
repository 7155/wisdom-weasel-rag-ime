# PAWOS 用户需求账本 · UR-151–UR-180

> 导航：[UR-121–UR-150](PAWOS_REQUIREMENTS_121_150.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-181](PAWOS_REQUIREMENTS_181_181.md)
>
> current 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-151 — Demo 剧本、截图与录制链路必须可重复且隐私安全

- **状态 / 优先级：** `current / P1 final delivery`
- Demo 记录前置条件、启动命令、确定性公开 fixture、操作步骤、画面 checkpoint、失败恢复、清理方式
  和产物路径。确定性 preview/fixture 负责可重复且隐私安全的宣传画面；真实安装与 Runtime 验收使用
  独立场景和收据，两者不得混写。
- 录制链路使用仓库内脚本或配置生成截图和视频，不依赖个人聊天、个人 Memory、凭据或不可追溯的
  手工窗口状态。产物记录 revision、viewport、数据来源与生成命令；失败时保留诊断信息但不提交日志、
  trace、个人路径或运行数据库。
- **用户可见验收：** 从干净 checkout 按文档命令可重新生成同一组关键截图并得到一个可播放的录制
  产物；中断后可安全重跑，默认不会修改真实个人历史。
- **原话依据：** “自己设计 Demo 剧本 → 自己把录制链路搭出来”。来源：当前任务，2026-08-27。

### UR-152 — README 宣传与截图必须逐项标明真实证据边界

- **状态 / 优先级：** `current / P1 final delivery`
- README 增加清晰的 PAWOS Showcase 入口、当前最强能力、关键截图与可运行命令，同时保留“尚无
  release-ready macOS binary”的真实警告。每张图片标明是公开 fixture、Web Runtime 还是已安装原生
  前台；视觉基线不得冒充安装、Runtime、foreground、签名或发布验收。
- 宣传文字只陈述当前 revision 已重新验证的 source/test/build/install/Runtime/foreground 层级，并链接
  已知限制、归属与复现步骤。历史 handoff、旧 commit 截图和过期 product-status 不能被改写为当前证据。
- **用户可见验收：** 新读者能在首屏理解产品中心、看到真实 PAWOS 画面、运行安全 Demo，并在同一
  位置看到证据等级与开放边界；截图不含个人数据、机器路径、密钥或未授权第三方内容。
- **原话依据：** “来补充readme宣传和截图”。来源：当前任务，2026-08-27。

### UR-153 — Steer、插入消息、用户回执与滚动位置必须属于同一条真实时间线

- **状态 / 优先级：** `current / P0`
- 普通用户消息、Steer、Assistant 思考、Tool 开始/完成和最终回复必须按权威
  `sequence` / 发生时间合并为**同一条时间线**，不能先按角色或 Turn 重新分组再渲染。
  用户在运行中插入 `ZDO` 时，如果它实际发生在“思考 B / Tool A”与“思考 C / Tool B”
  之间，就固定显示在那个位置；它仍属于正在运行的当前 Turn，不移动到 Composer 上方、
  本轮末尾、下一 Turn 或最终回复之后，也不能因刷新、补页或终态收敛而消失。
- 用户提交普通输入、Steer、等待输入回答后，时间线必须显示该次用户输入及其送达/
  生效回执；同一输入和最终 Assistant 回复都只出现一次。
- “跳到最新”只在用户明确点击时执行一次；流式增量、Tool 更新、pin/unpin、
  history 补页和回执合并不得造成闪烁、反复抢滚动或把刚插入的消息移位。
- **用户可见验收：** 分别发送普通消息、运行中 Steer 和结构化输入回答；三者
  都只出现一次并位于正确 Turn。离开底部时新事件不抢滚动；点击一次“最新”
  后稳定停在末尾。
- **原话依据：** “steer两个位置都不对，插入消息位置也不对”“输入完成得显示
  我的输入”“点击跳到最新一直闪烁”“消息闪烁”“一个插在中间发送的具体时候呀”
  “什么时候插入就把这个消息放到什么时候，就按照时间线，就只按照时间线”。
  来源：当前任务，2026-08-27 至 2026-08-28。

### UR-154 — Tool 失败、后台运行、调用计数与吞吐必须使用真实 Runtime 口径

- **状态 / 优先级：** `current / P0`
- 前台 Tool gateway 超时或一次命令退出非零时，若同一任务已转入 PAW 后台工具，
  UI 必须继续跟踪同一 run/job 并展示日志、完成或取消；不得因前台请求超时就把
  后台工作判为不存在，也不得静默重跑成第二个任务。
- 折叠摘要必须区分“可见步骤”“逻辑 Tool 调用次数”“Tool 种类”和“保留的
  Runtime 事件窗口”，不能把 8 次调用写成 8 个工具，也不能把 bounded window
  冒充完整总数。缺少稳定 call identity 时显式写未知/未关联。
- 当前模型调用的输入/输出 token/s 在模型输出和 Tool 阶段全程保持可见；第二次
  调用不得沿用第一次的速率，未知值不做动画伪造。
- **用户可见验收：** 同一长命令从启动、后台运行、日志到终态只有一个 runId；
  多次调用同一种 Tool 时调用数、种类数、事件窗口分别正确；Tool 行运行时仍能
  看到当前调用的 `input t/s` 与 `output t/s`。
- **原话依据：** “失败为什么他不后台调用工具，本项目支持后台工具的”“工具
  数量和实际不符合，实际应该有快100个了，最后显示只有16个”“13.8 t/s这种在
  输出过程中全程显示，即使是工具过程中，显示inoutt/s”。来源：当前任务，
  2026-08-27。

### UR-155 — Composer 支持图片粘贴，模型与推理使用一个不碰撞的组合控件

- **状态 / 优先级：** `current / P0`
- Composer 必须接收系统剪贴板中的图片，显示可移除预览，并通过既有媒体导入
  合同随消息发送；失败要保留草稿和可理解错误，不得吞掉粘贴。
- 当前控制要求是一个紧凑的“模型与推理”组合入口，在同一锚定浮层中分别选择
  模型和推理强度，并同时显示两者当前值。内部语义和图标仍可区分，但不得形成
  两个互相遮挡的控件、压住权限/身份/发送按钮，或在窄窗竖排错位。
- **修正关系：** 本条关于**单一组合入口**的要求 `supersedes UR-147` 中“不同
  入口和弹层”的旧布局；仍保留 UR-147 的独立语义、不同视觉标识、命中区不冲突
  和任何宽度不相撞要求。
- **用户可见验收：** 在宽窗与窄窗粘贴 PNG/JPEG 后可预览、发送和移除；组合
  控件一次展开即可更换模型或强度，任何状态都不覆盖相邻控件。
- **原话依据：** “无法粘贴图片，而且你没完成我之前说的，图标合并模型和思考
  强度，不能互相遮盖”。来源：当前任务，2026-08-27。

### UR-156 — Room 与 Session 共用同一工作面，多 Agent 默认稳定分列并可弹出完整行星 Session

- **状态 / 优先级：** `current / P0`
- Room 中每个 Partner 都是普通 Pi Session，复用 Session 的消息、思考、Tool、
  Composer、错误和终态显示，不再维护第二套 Room 卡片墙。并行时中央参考面按
  可用宽度稳定分列：例如 4 个 Agent 默认 4 列；不得按到达顺序在主时间线里一会
  插一位行星消息而打乱阅读。
- 普通 Room 仍是桌面中的一个 Room 工作窗口；用户可把任一 Partner Session 的完整
  行星窗口弹出/收回。进入“协作模式/协作姿态”时自动打开 **全部 Runtime 当前运行中的行星**，不再
  只恢复一个手动启用子集。行星为可见 Room Partner 主身份，subagent 保留其所属
  Session/运行身份，不伪装成新的 Room Partner。
- 宽度不足时用横向滚动、显式聚焦或渐进披露保留可读尺寸；统一字体、间距、
  Tool 披露和窗口 chrome 后优先显示更多真实内容，禁止通过缩到不可读来塞满。
- **术语与修正关系：** 本条细化并收敛 `UR-054`、`UR-058`、`UR-121` 与 `UR-149`；
  Room 特有的身份、公开关系、WorkItem 与治理仍保留，但对话 UI 不再分叉。最新
  “全部运行中行星”要求 `supersedes` 本条先前“只自动打开当前启用集合”的较窄解释。
  本条正文中的 Partner 窗口统一称为行星窗口；只有该 Session 内的 subagent 才称为卫星，
  下方原话中的历史称呼保留为来源证据。
- **用户可见验收：** 4 位 Partner 同时运行时默认看到 4 个稳定 Session 列；任一
  列可弹出/收回完整行星 Session 窗口；对应 Session 内的 subagent 可打开卫星；进入
  协作模式会一次打开所有当前运行行星，终态/未运行行星不冒充运行对象，主线不闪烁、
  不被行星窗口遮挡。
- **原话依据：** “！！！！！！room和seesion是同一的显示，不是两套ui”
  “room和seesion是同一的显示，不是两套ui”“多agent并行，就默认中心参考显示
  多个，比如4个ahgent就4列，然后窗口可以选择作为卫星窗口弹出”“room点协作
  姿态自动弹出启用的卫星”“要求room能展示行星，还有用户点击卫星的subagent
  也能展示”“当前主界面太乱了一会一个行星发一条。应该是刚才那种分列好一些”
  “协作模式自动弹出所有运行中行星”。
  来源：当前任务，2026-08-27。

### UR-157 — 新 Room 首次执行先确认一次，确认后默认无需逐 Tool 审批

- **状态 / 优先级：** `current / P0`
- 一个新协作 Room 收到首个可执行任务后，先显示对目标的公开理解、建议分工和
  “是否开始执行？”。用户确认前不得进入 Pi prompt、Tool、Partner dispatch 或
  私有 subagent；拒绝/修改保留草稿并允许重新对齐。
- 该确认是**开始执行确认**，不是逐 Tool 审批。确认后 collaboration Room 默认
  使用 `room_unrestricted`：授权工作区内所有已披露 Tool 持续运行，不再逐次弹
  审批；仍保留工作区边界、参数校验、OS 权限、Stop/cancel 与审计收据。
- 重试、刷新和同 client request 必须幂等，不能重复询问或伪造绕过；普通 Session
  不受 Room start gate 约束。
- **用户可见验收：** 首次任务只出现一次开始确认，确认前零执行事件；确认后原
  任务自动开始并持续推进，普通工作不再出现逐 Tool 审批框。
- **原话依据：** “room也有安全模式，，默认全部都不用审批”“oom也有安全模式，
  ，默认全部都不用审批。就是比全自动还无需审批，就是都能运行”“当前我是给他
  一个任务，他没有，询问是否开始，然后分配任务之后也没有。持续地跑”。来源：
  当前任务，2026-08-27。

### UR-158 — Room 只组合普通 Session，并只向新加入的 Room Session 注入一次身份上下文

- **状态 / 优先级：** `current / P0`
- Pi 仍是唯一 Agent Runtime；Room 只组合普通 Session、公开事件、分派、取消和
  一个 Root 结果。普通 Session prompt 必须是零 Room 注入，不得因仓库支持 Room
  就携带 Room 角色、治理或 WorkDocument 提示词。
- 只有 Session 新加入具体 Room 时注入一次有界 `room_bootstrap`，说明公开身份、
  当前目标/责任和必要 ContextRefs；后续 dispatch 只发送本次增量，不重复整份
  Room prompt、整段 Room 历史或文档正文。
- **用户可见验收：** 新建普通 Session 的 provider context 中不存在 Room 文案；
  新 Partner 第一次执行恰有一次 bootstrap，第二次及恢复后不重复，Room 的公开
  责任变化以有界增量送达。
- **原话依据：** “是那个 room 就是提示词的组合。就是我们现在要支持，其实是
  组合支入……如果是新的时候，就才注入这个，room相关的提示词。”“组合，。
  平时session就不注入”。来源：当前任务，2026-08-27。

### UR-159 — Room 主屏持续显示真实进展，四条证据轴互不冒充

- **状态 / 优先级：** `current / P0`
- 主 Room 必须持续给出“已完成、当前正在做、下一步、阻塞/待用户”的公开摘要，
  而不是只展示 Tool 卡或长篇 Partner 原文。WorkItem/需求文档有权威条目时显示
  哪些已勾选、哪些未完成及责任人。
- 进度分为 `implementation`、`validation`、`documentSync`、`resultDelivery`
  四轴；只有显式权威状态才可计数。WorkDocument 是可选语义记录，归档、不可写
  或同步滞后时标成 pending/attention/unknown，不得把实现/验证改成失败，也不得
  阻止一个真实 AgentResult 回传。
- 无明确总量时使用“进行中/等待/需要关注/未知”，禁止伪造百分比、`0/0` 或把
  Room `status=active` 冒充当前 Runtime 正在运行。
- **用户可见验收：** 执行中不打开行星 Session 窗口也能知道当前/下一步；完成一项后对应轴和
  文档条目立即收敛；文档同步失败时实现结果仍可交付且边界清楚。
- 完成或验收收据到达时，主 Room 内容区底部显示一次明确的结果卡，至少包含状态、摘要、
  证据/文件跳转；结果卡不得遮挡 Composer，流转记录为空时也不能留下大面积无意义空白。
  重复或迟到的同一收据必须幂等，不重复弹出结果。
- **原话依据：** “为什么运行没结果”“应该持续地告诉用户哪些完成了，中间，
  比如说主屏幕中间那个 兔兔之类的或者他那个 是有个文档嘛，需求文档，把那个
  需求文档艾特的勾了之类的。而且也看不到进度，也不知道在干什么。”“流程看
  不懂进度。也不知道文档哪些完成了”。来源：当前任务，2026-08-27。

### UR-160 — Room Stop 必须最终收敛并明确未停止对象

- **状态 / 优先级：** `current / P0`
- Stop 是 Room cancellation fan-out，不是隐藏窗口或只改前端状态。按
  `stopping → stopped | partial_stop` 单向收敛；任何迟到列表、snapshot 或事件
  都不得把状态降回 running。
- `partial_stop` 必须列出尚未确认停止的 Session、Tool job 或 Partner，以及可
  执行的重试/单独停止路径；已经停止和从未启动的对象不能被混入 pending。
- **用户可见验收：** 点击一次 Stop 后立即出现 stopping，最终稳定为 stopped 或
  partial_stop；刷新后保持同一终态，未停对象和下一步清楚可见。
- **原话依据：** “停止也有问题，流程看不懂进度。也不知道文档哪些完成了”。
  来源：当前任务，2026-08-27。

### UR-161 — 协作关系使用真实成功事件生成 DAG，失败尝试不画成成功边

- **状态 / 优先级：** `current / P1`
- 协作态势按 dispatch、handoff、review、merge 的权威成功事件形成有向无环图；
  节点是稳定行星/Session 身份，边标明关系和方向。发送失败、审批失败、Tool
  失败或仅有尝试记录不得进入成功 DAG，可在失败/阻塞区单独披露。
- 图在 4–8 位 Partner 与窄面板下仍可读；必要时按当前 WorkItem 聚焦，不用跨窗
  装饰线覆盖正文。
- **用户可见验收：** 同一 fixture 同时含成功与失败 dispatch 时，DAG 只出现
  成功边；节点、标签和箭头不互撞，能从当前任务回到完整图。
- **原话依据：** “画成dag图就好了”。来源：当前任务，2026-08-27；“检查当前
  为什么失败”“检查这个room的问题，包括上下文”作为失败诊断来源，不被当成
  成功关系。

### UR-162 — 桌面必须显示哪些 Session/Room 正在执行及其公开当前工作

- **状态 / 优先级：** `current / P1`
- Wayfinder/最近工作面增加紧凑“正在执行/需要关注”投影，显示对象类型、标题、
  真实状态、可公开的当前摘要及明确 WorkItem 计数；点击仍打开原 Session/Room。
  Dock 只表示 App 窗口，不得被改写成 Runtime 执行状态。
- 只有 Runtime-owned activity/sequence/asOf 能覆盖目录状态；列表刷新、最小化或
  关闭 Room 窗口不得让正在执行对象消失，迟到的 directory response 不得降级
  新事件。无明确总量时用不确定进行态，不做循环假进度条。
- Room 目录不得把所有历史 WorkItem 混成当前状态：只投影最新 root round；旧轮
  blocked/failed、同名旧 Room、已完成/取消/替代的工作不得把最新 Room 永久染红。
  `failed` 终态保留在结果/完成度中，但只有当前未收束 blocker 或 Runtime 明确
  fault 才显示“需要关注”；sequence gap/快照恢复显示中性的“同步中/状态未知”。
- **用户可见验收：** 最小化或关闭一个仍在执行的 Room 后，桌面仍显示其公开
  当前工作；完成/失败后文字和可访问状态及时收敛，颜色点不是唯一提示。
- **原话依据：** “桌面得显示哪些对话正在执行，正在干什么，加动画或者进度条
  之类的”“room全是红的”。来源：当前任务，2026-08-27。

### UR-163 — 当前 Squirrel、Pi Runtime、MLX 与 PAWOS 前端一起更新；Browser 只发布 Electron

- **状态 / 优先级：** `current / P0 delivery`
- 使用产品安装链从当前锁定源码更新 Squirrel、managed Pi Runtime、MLX predictor
  和 Control/前端；保留用户数据库、模型、个人配置、浏览器 profile、输入历史和
  旧 Pi generation。源码、构建、安装、服务健康与真实前台分别出具收据。
- 安装前记录当前 marker/pointer 并创建可恢复的代码快照；安装失败不得留下混合
  generation。dirty development build 必须明确标记，不得冒充 clean release。
- Browser 的可恢复回退只能是已验证的历史 Electron 构建、源码 commit 或独立备份，
  不能再构建、安装、发现或宣传 Swift/WebKit Host 或 Swift fallback App。通用
  `RagImeControl.app` 产品身份保留，但其唯一发布宿主是 Electron/Ego/CDP。
- Git 提交/推送是安装后的独立交付动作；只处理本任务路径并验证远端账户，不能
  把无关 dirty 文件混入。
- **修正关系：** 本条最新 Browser 约束 `supersedes` 任何把 Swift Host 作为旧前端
  fallback 的解释；它不撤销旧 Pi generation、用户数据或历史 Electron 包的可恢复性。
- **用户可见验收：** 安装审计能识别四个新组件来源，三个服务健康且前台打开的
  PAWOS 是本轮 UI；旧代码快照和旧 Pi pointer 可定位，用户数据量/路径未被替换；
  安装目录、build marker、发布脚本与 Runtime Browser 检测均不存在 Swift fallback。
- **原话依据：** “更新 Squirrel、Pi Runtime、MLX”“安装”“当前版本的就到main”
  “git push 到mian”“Swift 只作为 fallback不要，去除掉”。来源：当前任务，2026-08-27。

### UR-164 — Runtime Skill 只保留执行所需方法，不加载来源说明和开发对话

- **状态 / 优先级：** `current / P1 context quality`
- 整体审计实际随 managed Pi Runtime 加载的 Skill 正文及其可达 references。删除作者、
  方法来源、上游 commit、迁移过程、开发时交谈和重复的通用工作流说明；来源或许可证
  若依法必须保留，应放在不注入 Agent 上下文的元数据/许可文件中。
- 保留每个 Skill 独有且可执行的方法、状态机、安全边界、真实失败模式、验收规则和不
  重复的正反例。Ego Browser Skill 只说明可用能力、调用合同、结果与失败；不得要求
  Agent 判断“内部/外部浏览器”或加载当时选型争论。
- **用户可见验收：** 所有 Runtime Skill 可通过结构校验和相关回归，加载字符/token
  明显下降；全文检索不再命中 Matt Pocock、upstream commit、method provenance、
  development history 或 Ego 选型对话，而独有反例和操作约束仍可找到。
- **原话依据：** “检查技能，移除这些来源说明，还有ego啥的。来源说明对上下文无用”
  “这个Ego这个技能就把当时很多做的时候的交谈给它塞到技能里面了”“Skill得检查
  整体”“反向示例可以保留，不要重复就行”。来源：当前任务，2026-08-27。

### UR-165 — Memory 整理任务重启后必须收敛，不能永久显示排队或运行

- **状态 / 优先级：** `current / P0`
- Gateway/Sidecar 重启、浏览器刷新或进程内 job registry 丢失后，旧 `jobId` 必须返回
  明确终态（interrupted/failed/resumable），前端停止轮询和旋转；不得继续显示“已进入
  队列，等待开始”，也不得伪造完成。
- durable model run 与 job/run identity 必须可追溯；安全重试复用或显式恢复同一冻结输入，
  不重复写入已完成日期。错误状态保留“重新整理/恢复”操作和原始 runId。
- **用户可见验收：** 在整理中重启 Gateway 后，旧卡片在一次状态读取内收敛为中断/可恢复；
  点击恢复后要么继续到真实终态，要么给出可操作失败，不再无限转圈。
- **原话依据：** “这个整理一直整理不动”。来源：当前任务，2026-08-27。

### UR-166 — Memory 整理提供独立、可读、逐阶段计时的 Trace

- **状态 / 优先级：** `current / P1 observability`
- 每次整理以独立 Trace 展示实际公开输入对话/上下文、requested/effective 模型与推理强度、
  Skill/Tool 配置、公开 Tool 调用与有界结果、候选生成、复核、写入、失败和恢复；没有
  Skill/Tool 时明确显示 `none`，不得凭空补齐。
- 每个阶段记录 queue/start/end/duration，允许并行 span 并区分 wall-clock 与各 span 耗时。
  列表只显示 runId、状态、时间和摘要；用户显式打开详情后才读取本机有界内容。凭据、
  隐藏推理、个人绝对路径和未授权原文必须脱敏，但公开对话不能被“安全”名义全部隐藏。
- **用户可见验收：** 从 Memory 时间线可打开任一整理 run，按时间看清输入、模型、配置、
  每一步、结果和耗时，并能定位停滞/失败发生在哪一阶段。
- **原话依据：** “这个就单独作为一个框，一个trace，显示怎么整理的技能，输入的上下文
  是什么，就把那个对话就给它弄出来”“直接就把他这个对话给他显示出来，然后输出什么
  什么调的工具”“得显示每一步的时间”。来源：当前任务，2026-08-27。

### UR-167 — 对话 Memory 召回与 Knowledge 检索使用同一 Trace 语法并解释最终注入

- **状态 / 优先级：** `current / P0 observability`
- Memory recall 与 document Knowledge 保持不同数据 authority，但复用同一 Trace envelope，
  并绑定 `sessionId + turnId + traceId`。Agent 时间线收据可反向打开 Trace，Trace 也能回到
  触发它的对话 Turn。
- Trace 展示原查询及规范化、命中的 Book/Atom/文档/图节点、embedding provider/model/
  dimensions/fingerprint、dense/cosine、BM25 lexical、图/网络每一跳、融合、去重、阈值、
  rerank、最终排名，以及“命中但未注入”和“最终注入”的明确原因。未知分数/耗时显示
  unavailable，不伪造 0 或百分比。
- queue、embedding、dense、BM25、每个 graph/network hop、fusion、rerank、filter/dedup、
  context assembly 都记录独立耗时；并行阶段不得相加冒充端到端 wall-clock。隐藏推理和凭据
  不进入 Trace。
- **用户可见验收：** 对一个新对话发问后，用户能从召回收据看出为何命中哪些 Books/Atoms
  或 Knowledge 节点、各通道分数与耗时、哪些证据最终进入模型上下文，以及没有进入的原因。
- **原话依据：** “记忆也是得Trace”“记忆整理整理是有两个trace”“比如说它是因为什么把
  它召回的”“命中了哪些book，或者命中了网络的哪些节点，又构造了什么embedding”
  “比如ebeding搜索时间，网络多跳的结果”。来源：当前任务，2026-08-27。

### UR-168 — Trace 支持手动/周期 AI Eval，并区分真实指标与 AI 估计

- **状态 / 优先级：** `current / P1 evaluation`
- 用户可手动运行或按日/周期把选定 Trace 集合交给独立 AI Judge。默认 requested evaluator
  为 `GPT-5.6 Luna`、thinking `Max`（界面文案“Luna Max”），并记录实际 effective
  provider/model/thinking、judge prompt/rubric version、输入 Trace fingerprint、时间、延迟和
  成本；回退或不可用必须显式。
- 只有带 human/frozen ground truth 的数据集才计算并展示 Accuracy、Precision、Recall、F1、
  Recall@K、MRR 或 nDCG。无标注线上 Trace 只展示带“AI 评审估计”标签的 relevance、
  coverage、groundedness、contradiction 和 confidence，不得冒充真实准确率或召回率。
- Eval 与原 Trace 双向链接，显示周期趋势、失败案例、依据覆盖、版本回归与样本/分层范围。
  Judge 只给建议和报告，不得自动修改 Memory、Knowledge、索引、阈值或 Agent 答案。
- **用户可见验收：** Trace 界面可选择样本并用 Luna Max 运行评测，也可设置周期；有标准答案
  时看到可复算指标，无标准答案时只看到明确标注的估计；每个分数都能回到 case、Trace 和
  支撑/反驳证据。
- **原话依据：** “这个Trace，每天或者周期性的交给一个AI来判断这个系统是否有效”
  “支持由AI来输出一个那个什么准确率、召回率、F1，然后或者最后得出的结果是否都有依据”
  “eval模型默认luan max”。来源：当前任务，2026-08-27。

### UR-169 — 输入法显式生成必须获得可配置的近期输入与当前屏幕上下文并进入 Trace/Eval

- **状态 / 优先级：** `current / P1 observability`
- “生成”按钮的显式输入流程同时装配当前选中/输入内容、有界近期用户输入，以及
  当前前台网页/应用的 Accessibility 语义上下文；不能只读取聚焦输入框就假装已经
  获得页面。安全输入、密码、凭据和明确敏感节点仍 fail closed。
- PAWOS 设置提供近期输入条数/字符数和 AX 节点数/字符数预算。每次执行记录 requested/
  effective 数量、实际字符/节点、截断、不可用原因、前台 App/窗口的安全身份、capture
  时间与各阶段耗时；预算扩大后仍保持确定上限，不读取隐藏 DOM 或未授权窗口内容。
- 统一 Trace 使用明确 `sourceKind=input_generation`，展示当前上下文、近期输入、Memory/
  Knowledge 召回、模型生成和最终输出的公开收据；记录最近输出时间、成功/失败/取消，
  并可纳入 UR-168 的手动/周期 Eval，不能与被动 prediction 混为一类。
- **用户可见验收：** 在 GPT 网页等页面触发生成时，详情能看到实际获得的页面语义与近期
  输入数量；拿不到页面时明确 unavailable；设置改变后 effective 预算和 Trace 同步变化；
  最近一次输出的时间与结果真实可见。
- **原话依据：** “生成按钮，我需要，要稍稍问，多输入一点最近输入。还有多输入一点，
  当前屏幕的内容”“OS APP 里面可以设置吗？就是什么数量，还有 x 数”“输入法的也加入
  eavl。检查最近输出时间和是否成功”。来源：当前任务，2026-08-27。

### UR-170 — Room 每轮使用一张稳定行星任务表，详情通过完整行星 Session 窗口展开

- **状态 / 优先级：** `current / P0 Room presentation`
- Room 主界面是一个 Room 窗口和一个底部 Room composer；普通 Room 中点击行星会在桌面中弹出
  该行星的完整 Partner Session 窗口；行星没有各自输入框，也不把四个
  完整 Session 窗口常驻主屏。Room 与 Session 复用同一消息/活动/Tool/结果视觉语法，但
  Room 用组合投影组织多 Session，不建立第二套 Runtime 或第二套聊天 UI。
- Room 主窗口的重新设计是独立且必须完成的交付，不得以“已经能打开行星窗口”代替。主窗口与完整行星 Session
  的信息分工、round sheet 密度、滚动和展开方式须先形成可评审设计，再落生产布局；handoff
  必须将尚未完成的 Room 重设计明确列出，不能把现有四列/卡片墙当成最终设计。
- 每次用户 Room 输入形成一张可滚动、可折叠的 round sheet。按稳定行星身份一行更新，禁止
  四路结果按时间交错刷屏。每行至少显示：行星、当前任务、阶段/状态、最新公开进展；阻塞
  时显示原因与恢复操作；完成时显示摘要、结果/证据文件；末尾始终有“打开行星 Session”。同一行星
  在一轮内的后续子任务进入行内历史披露，不复制整张顶层卡。
- 点击行星或“打开行星 Session”必须打开对应真实 Partner Session 窗口，用于查看完整公开时间线、
  Tool/Trace、失败回执、WorkDocument/结果证据和调试信息。该窗口不拥有独立 composer；需要
  继续输入时回到 Room composer 并预填 `@行星`，避免产生两条相互竞争的用户输入通道。
- **身份显示修正：** Room 主表、协同图、行星 Session 窗口标题与正文只使用稳定行星名和任务/分工语义，
  不显示 Partner 的人名或 persona `displayName`。人名若仍存在于 Runtime 配置，只作为内部绑定数据，
  不能成为 Room 视觉身份，也不能与行星名并排出现。
- 只有流式模型输出期间显示输入/输出 t/s，终态整块消失；模型与推理强度合并为一个不碰撞的
  组合入口；执行模式显示“全部通过/无需逐项审批”。原生与 Web chrome 合并成一个窗口框。
- **用户可见验收：** 四位 Partner 同时工作时，主屏仍只出现一张本轮表且各行原地收敛；
  用户滚动可回看旧轮；完整行星 Session 窗口能从对应行打开并回到准确 Room/@伙伴；主屏不再
  出现四个 composer、双框、完成后 t/s 或交错刷新的长篇 Partner 原文。
- **原话依据：** “模型和推理强度还没合一，行星不要对话框，room来输入”“一个框，不要两个”
  “Earth｜当前任务｜阶段｜最新进展｜打开卫星……这些的详情就可以卫星窗口查看”“这个一轮
  对话可能就得一个这个表”“要那个打开这个卫星对话框，卫星要能打开，这样做才能trace和
  deubg”“room我讨论好再做，卫星窗口怎么显示，主窗口显示什么”“room的重新设计窗口呢”。
  来源：当前任务，2026-08-27；“人名本来就不要”。来源：当前任务，2026-08-28。

### UR-171 — PAWOS 桌面以虚拟项目文件夹和对话文件呈现 Session / Room

- **状态 / 优先级：** `current / P1 desktop information architecture`
- PAWOS 桌面不再只用传统对话列表承载查找。一个项目显示为一个可点击、可原地展开/折叠的
  **虚拟文件夹**；展开后显示属于该项目的 Session 与 Room **对话文件**。文件行至少投影可公开的
  标题、对象类型、真实运行状态、当前进度、阻塞和最近结果；权威投影没有提供的字段显示未知/不可用，
  不能根据聊天文案猜测“完成”。
- 点击对话文件打开或唤起同一 canonical `sessionId` / `roomId` 的真实工作窗口；文件夹、搜索、排序、
  展开状态只是 PAWOS OS 的浏览与定位语法，不复制 transcript，不创建第二个 Session/Room 实体。
- **文件系统边界：** 这些项目文件夹与对话文件仅存在于 PAWOS OS 的显示投影，**不要求且不得默认写成
  Finder 文件、Git 目录或 Markdown transcript**，也不成为新的持久化/完成状态权威。现有 Runtime、
  Session transcript、Room 事件、WorkDocument 与 Git 各自继续拥有原数据；Files App 若展示同一对象，
  也只能按稳定 ID 反向打开权威对象。
- **语义修正：** 这不是把“一岛一 Room”强制改成“一岛一项目”，也不是重新切分系统/项目设置 owner；
  “文件夹”首先是用户直观看见对话与状态进度的 OS 表达。
- **视觉基准而非配色规范：** 用户截图中的 macOS Finder 式桌面文件夹网格用于确定“文件夹对象、项目
  标签、状态提示、点击展开”的直观空间语法；蓝色不是固定要求。可以探索紫色玻璃、自然材质、岛屿
  融合或其他与 PAWOS 整体美术一致的方案，先用多套可运行原型讨论再选择，不能照抄 macOS 蓝色文件夹。
- **用户可见验收：** 在 PAWOS 桌面点击一个项目文件夹后，对话文件原地展开；打开其中一个 Session 与
  一个 Room 时进入正确的现有对象，状态/进度随权威投影更新；Finder 与 Git 不出现镜像对话文件。
- **原话依据：** “把对话作为文件放到桌面，当作文件系统管理，例如一个项目的对话就放一个文件夹，
  文件夹点击就展开”“因为传统的列表式对话不方便查看查找。文件更方便。”“文件夹只是os的显示而已，
  分别用户直观看到对话和状态进度”“是这种文件夹”“风格不一定要蓝色这种”。
  来源：当前任务，2026-08-27 至 2026-08-28。

### UR-172 — Room 默认使用逐轮行星任务表，行星行可展开并打开真实 Partner 行星 Session

- **状态 / 优先级：** `current / P0 Room primary surface`
- 本条延伸并收敛 `UR-170`：每次用户 Room 输入只新增一张具有稳定 `roomTurnId` 的可滚动、可折叠
  行星任务表；每个 Partner 在该轮只占一条稳定行，后续状态、进展、Tool 摘要、阻塞、复核和结果在
  原行更新或进入行内历史，不按事件到达顺序把四路长消息交错插入主阅读流。
- 表头承担本轮用户目标、整体状态和收起/展开；行摘要承担行星身份、当前任务、阶段、最新公开进展与
  恢复/结果动作。展开具体行显示该 Partner 本轮的有界公开事件与证据，完整 transcript、Tool、Trace、
  失败回执和调试信息仍由真实 Partner Session 窗口承载。
- 点击行星身份、行主体或“打开行星 Session”打开/唤起绑定该 Partner Session ID 的真实行星 Session
  对话窗口；已经打开的窗口只提升层级并聚焦，不创建副本。该窗口保持 `UR-170` 的单一输入边界：
  不拥有与 Room composer
  竞争的独立 composer，需要继续输入时回到 Room 并预填准确的 `@行星`。
- **关系修正：** `UR-156` 的“默认多列完整 Session”不再控制 Room 默认主视图；多窗口同时出现属于
  `UR-177` 的显式协同模式。普通状态下以本条的一轮一表为主，Session 视觉语法仍复用而非分叉。
- **用户可见验收：** 四位 Partner 并行工作时，本轮表只有四条稳定行且原地收敛；旧轮可滚动回看并
  独立折叠；点击任一行能打开准确行星 Session 并返回准确 Room / `@行星`，主窗口不发生四路刷屏。
- **原话依据：** “每轮用户输入形成一张可滚动、折叠的行星任务表，各行原地更新，不能四路消息交错
  刷屏。”“可滚动、折叠的行星任务表，这个点击具体行星就是跳转或者弹出行星对话窗口。这些行星窗口
  表看看怎么表达。”来源：当前任务，2026-08-27。

### UR-173 — 行星“引力”以真实协作事件投影为可读 Workflow 图

- **状态 / 优先级：** `current / P0 Room collaboration projection`
- Room 的行星“引力”不是装饰连线，而是从权威公开事件投影出的有向协作关系：相互 `@`、任务分派、
  回复/回执、交接、复核请求与复核结论。每条关系可追溯到 source/target Partner、`roomTurnId`、
  WorkItem/Dispatch/事件 ID、公开摘要、时间顺序和当前状态。
- 已发出、已送达、已接收、失败、取消与完成必须视觉和文字分离；只有权威成功/确认事件才能成为
  “已建立”的引力边，pending/失败不能画成成功。边粗细、颜色或动画如表达次数/状态，必须由真实事件
  聚合规则得到并能解释，不能推断伙伴心理或伪造通信。
- 关系视图采用类似清晰流程图 / Coze workflow 的节点、方向、阶段与工作项组织；默认按当前轮、所选
  WorkItem 或所选行星聚焦并渐进披露，避免所有历史边同时出现形成线团。图旁保留可访问的文字关系列表，
  reduced-motion、键盘和窄窗下仍能检查同一收据。
- 点击节点可聚焦/打开对应行星窗口，点击边可查看形成该关系的公开事件和证据；若节点明确代表
  行星 Session 内的 subagent，则打开该 subagent 卫星；图与任务表双向联动，但
  都只是 Room 事件的只读投影，不建立第二套协作日志或执行状态。
- **用户可见验收：** 在真实发生 `Earth @ Mars → dispatch → handoff → review → receipt` 的一轮中，
  图能按方向和状态读出完整关系并逐边回到原事件；不存在的关系不出现，失败边不冒充已完成。
- **原话依据：** “我希望还能看到行星间的引力（相互@，任务分派）”“我还有那个可视化是类似于
  流程图或者coze那种图，清晰明了”。来源：当前任务，2026-08-27 至 2026-08-28。

### UR-174 — Trace / Eval 是所有 Agent 能力与垂直应用复用的平台基础设施

- **状态 / 优先级：** `current / P0 platform foundation`
- `UR-166`–`UR-169` 的 Memory、Knowledge、Eval 与输入生成 Trace 是首批垂直切片，不是四套特例。
  系统建立一个可扩展的公共 Trace envelope、span/event/artifact 语法、producer registry、持久化查询、
  隐私/预算策略和 Trace ↔ 原对象返回链接；Session、Room、Tool、Browser、Memory、Knowledge、RAG、
  输入生成以及后续垂直 Agent 应用都复用它。
- 公共 envelope 至少支持稳定 `traceId`、parent/link、source kind、Session/Room/Turn/WorkItem/run/case
  关联、requested/effective 模型/Tool/配置版本、queue/start/end/duration/status、公开输入/输出 artifact
  引用、错误/取消/恢复与生产者 schema version。领域阶段通过类型化 span 扩展，不能把所有 payload
  塞成不可验证的任意 JSON；未知字段显示 unavailable，不伪造 `0`。
- Trace 是可查询数据与运行合同，不只是某个页面上的卡片。每个代表性生产者先证明真实端到端链路，
  再由统一 UI 浏览/过滤/比较；确定性 CRUD 或没有模型/检索意义的操作可明确标注 Eval `N/A`，不得为
  追求“全覆盖”生成假 Trace。
- Eval 复用同一 case/dataset/run/schedule 合同，支持手动、周期与回归比较。带 human/frozen ground
  truth 才展示可复算准确率、Precision/Recall/F1、Recall@K/MRR/nDCG 等真实指标；无标注 Trace 的
  Judge 结果必须标注为 AI 估计并保留模型、rubric、证据、置信度、成本与回退。
- RAG、Memory 召回/整理、Knowledge 检索必须作为首批检测对象，覆盖检索命中、过滤/融合/rerank、
  最终注入、答案依据、延迟、失败与版本回归；Eval/Judge 只能出报告，不能绕过 owner 自动改写 Memory、
  Knowledge、索引、阈值、Room 或答案。
- **用户可见验收：** 从 Session/Room/Tool/Browser 和 RAG/Memory/Knowledge/input 各运行至少一个真实
  代表场景，能用同一入口查到关联 Trace、回到原对象并启动同一 Eval 流程；指标标签和证据边界正确，
  新 source kind 可通过公共扩展点接入而不是复制整套后端/前端。
- **原话依据：** “Trace / Eval得做通整个系统，因为后续很多开发得有eavl。”“trace得做通，因为后续
  我开发垂直类的agent的应用需要tarce基础，所以现在就得打好地基”“还有rag，记忆这些的检测”。
  来源：当前任务，2026-08-27 至 2026-08-28。

### UR-175 — 岛屿与设置只做渐进美术整合，不改变数据与设置权威

- **状态 / 优先级：** `current / P2 design exploration`
- 可以逐步尝试把系统设置入口融入既有“控制岛”视觉语言，并在项目文件夹/项目场景内提供上下文设置
  入口；先以草图、可运行原型和真实对象投影讨论信息层级、材质、展开方式与动效，再决定生产形态。
- 岛屿是 PAWOS 的美术与空间导航隐喻，不自动意味着“一岛一项目”“一岛一 Room”，也不重新定义
  Settings、Project、Session、Room 或 Runtime 的 owner。全局设置与项目相关设置仍由现有 schema/
  authority 决定，同一值不能因两个入口变成两份。
- 该探索不得阻塞 P0 Room 与 Trace/Eval 地基，也不得把愿景说明、假状态或装饰交互写进生产界面。
- **原话依据：** “这个美术和设计我们讨论一下，我感觉设置可以融入我们之前设置那个岛啥的”
  “这些需求你记录，后续慢慢尝试就好。”以及对语义追问的纠正：“这些是什么意思，文件夹只是os的
  显示而已”。来源：当前任务，2026-08-27。

### UR-176 — 垂直 Agent 应用可在受治理沙盒中自建、自测、自查 Trace 与自评

- **状态 / 优先级：** `current / P1 vertical Agent platform`
- 在 `UR-174` 地基之上，未来的开发 Agent 必须能为一个垂直应用创建有版本的应用/能力定义与工作区，
  在受治理沙盒中构建、运行代表用例、采集自身 Trace、执行确定性测试和 Eval、定位失败并迭代产物；
  不能靠读 UI 文案宣称“自测通过”，也不能把私有 Agent 推理当作 Trace。
- 沙盒明确文件系统根、网络/凭据/Tool 能力、资源与时间预算、依赖来源、Stop/cancel、恢复、输出 artifact
  和 promotion 边界。Agent 可在授权工作区内修改候选应用，但安装、启用、数据写回和生产发布仍需要
  各自 owner/批准；沙盒成功不冒充安装、Runtime 或前台验收。
- 垂直应用复用公共 trace producer、case/dataset、ground truth、Judge、回归比较和证据收据，并能定义
  自己的类型化领域 span/指标/rubric。平台应提供最小 SDK/模板与示例，而不是要求每个应用复制
  `trace_eval.py`、数据库表、路由和 UI。
- 首批示例候选保留用户点名的 **`sgg` 文件夹示例**、**“掌柜问数”** 和 **RAG Agent 自测/自构建**；
  `sgg` 的准确路径/含义及示例先后可在实现前通过仓库事实或用户确认收敛，不能擅自改名或假装现有
  仓库已经包含它们。至少一个真实小型垂直应用需跑通“构建 → 沙盒运行 → Trace → 测试/Eval →
  失败定位/再运行”的闭环，再以第二个不同领域消费者证明地基可复用。
- **原话依据：** “例如开发sgg文件夹的示例，掌柜问数之类的”“我之后是准备agent能自己开发垂直
  应用，自己评测检查trace，准备沙盒之类的，就像rag的agent自己测试和自己构建”。来源：当前任务，
  2026-08-28。

### UR-177 — Room 右上角提供显式协同模式并打开全部运行中行星

- **状态 / 优先级：** `current / P0 Room collaboration mode`
- Room 默认保持 `UR-172` 的单窗口逐轮任务表；右上角提供清楚的视图/姿态切换，其中第二个选项是
  **协同模式**。这不是隐藏自动行为，也不由当前选中的行星数量决定。
- 进入协同模式时，按权威 Runtime active projection 一次打开或唤起**全部当前运行中的 Room Partner
  行星**；已开窗口只聚焦/编排，不重复实例。不得继续保留 `slice(0, 5)`、固定上限或“启用行星”子集，
  也不得把终态、未开始、detached intercom 或私有 subagent 冒充运行中 Room Partner。
- 同一模式同时提供 `UR-173` 的清晰协作 Workflow/引力视图，并用可解释的窗口编排、overview/聚焦与
  返回主 Room 操作避免行星窗口遮住任务表。某一行星窗口打开失败时保留逐行失败/重试回执，不能让其余已成功
  窗口或 Room 执行消失。
- **用户可见验收：** 当 2、4 和超过 5 个 Partner 真实运行时，点击右上角协同模式分别唤起全部 2、4、
  N 个运行中行星且没有重复；退出/返回默认视图后仍能定位同一轮任务表和同一 Partner Session。
- **修正关系：** 本条保留 `UR-156` 的“全部 Runtime 当前运行中的行星”语义，取代任何只开五个、只开
  用户启用集合或默认四列常驻的实现解释。
- **原话依据：** “反正右上角有按钮，第二个协同模式就可以弹出所有行星”。来源：当前任务，
  2026-08-28。

### UR-178 — 垂直 Agent 沙箱以可安装 Connector 插件呈现，并保留核心执行权威

- **状态 / 优先级：** `current / P1 vertical Agent showcase`
- 沙箱能力在 PAWOS App Center / 能力市场中以可发现、安装、启用、停用、更新和回滚的第一方
  Pi Package 呈现，便于面试时直观看见能力接入和生命周期；不得为此建立第二套 Package loader。
- Package 中的扩展只负责注册模型可见的 Sandbox Connector Tool、声明能力和调用受 Session 限定的
  PAW Tool Gateway。Docker、macOS Seatbelt 或未来 VM backend 的进程执行、工作区范围、网络策略、
  Stop/cancel、输出收据、Trace 校验、TraceStore 与 EvalRunStore 写入仍由 PAW 核心 owner 负责；
  插件不得直接启动任意宿主进程、持有数据库句柄或自行把 Agent 声明写成权威 Eval。
- 首个展示版本只需要一个真实可运行的第一方 Connector 和一个小型垂直应用闭环，不先搭多 backend
  通用框架。安装并启用后，新 Session 能调用它运行 `sgg` 或“掌柜问数”示例，并在同一结果中打开
  SandboxRun、Trace 和 Eval；停用后，新 Session 不再得到该 Tool，已有 Session 保持 Pi Package 的
  稳定资源快照语义。
- **用户可见验收：** 面试演示中可依次完成“App Center 查看 Connector → 安装/启用 → 新建 Session
  运行垂直示例 → 查看沙箱状态与真实 Trace/Eval → 停用或回滚”；界面明确区分 Package 生命周期、
  沙箱执行成功、源码测试和已安装前台验收，任何一层都不冒充另一层。
- **原话依据：** “沙箱可以作为插件吗，我也是面试展示，”。来源：当前任务，2026-08-28。

### UR-179 — 网页模型必须通过可校验选择链定位每个功能的真实前端

- **状态 / 优先级：** `current / P0 web-model handoff authority`
- 为前端介绍页、展示页或后续网页模型提供一份单一、机器可读且可人工导航的前端 source map。每个
  PAWOS App/功能必须记录当前产品入口、App registry identity、实际 dispatch/selection chain、叶子
  render owner、style owner、宿主或原生 build evidence、展示 route 与证据等级；禁止继续通过文件名、
  搜索排序、截图外观或旧 handoff 猜“哪个前端是真的”。
- React PAWOS、Electron Browser guest、原生 Control WebHost、patched Squirrel Assistant Overlay 和
  SwiftUI Voice Overlay 必须分别描述。Room 仍属于 Agent，Wayfinder 属于桌面表面，WKWebView 只复用
  同一 React 产物；不得因宿主或 reference HTML 存在而发明第二套产品 UI。
- Preview transport、fixture/seed、测试、静态 HTML/PNG、生成合同、`dist`、历史文档和显式 prototype
  fallback 必须列入非权威排除项。模型找不到从默认入口/dispatch 或原生构建脚本到文件的真实链路时，
  只能报告 `unverified`，不得挑一个“看起来像”的候选。
- source map 需要自动检查 11 App registry 对齐、owner 路径存在、选择/构建标记仍存在，以及权威 owner
  未落入 preview/docs/test/dist 等区域。源码选择、构建接线、安装、运行、前台交互和用户审美接受仍
  分层记录，任何 source map 或检查通过都不冒充后四层验收。
- **用户可见验收：** 网页模型只需从 `control-center-web/CLOUD_MODEL.md` 进入 source map，即可为任一
  App/原生表面先返回“功能 → selection chain → render/style owner → 排除项 → proof level”，再使用真实
  源码构建介绍页；故意删除一个 App、改掉 dispatch 标记或把 preview 文件设为 owner 时检查器失败。
- **原话依据：** “目前正在做前端介绍页面，会需要真实前代代码做网页展示各个功能，可是网页模型老是
  找错，怎么告诉他每一个功能的真实前端”。来源：当前任务，2026-08-28。

### UR-180 — 桌面 Trace Agent App 负责跨系统诊断、报告与证据化自我优化

- **状态 / 优先级：** `current / P1 Trace Agent foundation`
- PAWOS 桌面提供一个独立、可打开的 **Trace Agent App**。它不是把现有运行记录页面换一个名字，也不
  另建第二套 Runtime；它消费 `UR-166`–`UR-169`、`UR-174` 已确立的公共 Trace/TraceStore/EvalRun
  权威，持续发现并解释系统中“失败、卡住、质量下降或行为不符合预期”的真实事件。
- 首批诊断范围包括：Tool 调用失败、子 Agent/Session/Room/垂直应用运行失败、Provider/Runtime 错误、
  Memory 召回质量、Knowledge/RAG 的解析/检索/排序效果，以及可由 Eval 支持的检索参数与策略优化。
  每份报告至少说明现象、影响范围、基于 Trace 的可能根因与置信/证据边界、相关 run/span/文件、建议动作，
  并允许从桌面报告直接跳回准确 Trace、失败运行和可打开的结果文件；不能只显示“失败”或打开整段
  Session 后让用户自己找。
- Trace Agent App 允许用户从当前或历史对象中选择任意一个 Session、Room 或垂直应用运行作为诊断输入；
  选择 Room 时必须关联该 Room 的主持 Session、全部行星 Session、子 Agent、WorkItem、公开流转、Tool
  调用和 Token/上下文使用，而不是只分析当前可见消息。除错误定位外，它还要识别上下文遗漏或污染、
  任务拆分与分配不合理、重复打回、重复 Tool 调用、无效等待、冗余流程和不成比例的 Token 消耗，并说明
  “哪一步为什么浪费、由什么证据支持、怎样重新分工或删减流程”。
- “任意当前或历史对象”必须通过服务端真实游标分页或搜索实现，不能被固定 200/500 条上限截断，也不能
  只扩大一次性 `limit`。加载更多时按服务端游标继续读取，跨页按 canonical ID 合并去重并保留 Room/Session/
  run 关联；分页或读取失败时显示可操作的真实原因。
- Trace Agent 必须加载专用的 `trace-agent-diagnostics` Skill，形成可复用的高效排查方法，而不是每次从日志
  猜测。Skill 至少路由 Tool/Browser/Runtime、WorkDocument、Context、Room 分工与返工、Token/延迟、
  Memory、Knowledge/RAG 七类诊断；固定“选择并限界对象 → 关联权威 Trace/Eval → 区分观察/假设/根因 →
  单变量对照或沙箱重放 → 证据化报告 → 授权后修改与前后 Eval”工作形状，并持续用真实失败案例改进。
- Trace Agent 可生成候选修复、索引/参数优化或评测计划，并在 `UR-176`/`UR-178` 的受治理沙箱中重放
  代表用例，形成“发现 → 归因 → 候选改动 → 沙箱验证 → Eval 前后对比 → 桌面报告”的自我优化闭环。
  未经真实重放/Eval 支持的建议必须标为假设；候选成功不冒充已经应用或前台已验收，应用后继续观察
  同一指标并保留回退依据。用户明确授权后，Trace Agent 可以修改对应代码、配置、Prompt、路由或评测
  参数，但修改动作必须作为普通 Agent 工作留下文件 diff、验证结果和可回跳 Trace，不能静默自改。
- 报告作为 PAWOS 文件系统中的真实可见桌面对象，支持按项目、时间、领域、严重度和处理状态归档、搜索、
  折叠与再次打开；它引用权威事件和 artifact，不复制完整私有 transcript，也不要求 Finder/Git 文件语义。
- **首条纵向验收：** 一次真实子 Agent 失败必须在原卡片显示具体失败原因，点击详情弹出/复用该子 Agent
  卫星窗口，点击 Trace 精确过滤到该 `runId` 的事件；Trace Agent 随后能生成一份含根因证据、建议动作和
  回跳链接的桌面报告。再分别用一组 Memory 召回 Eval 与一组 Knowledge/RAG Eval 证明相同 App 能报告
  质量问题和改前/改后差异。
- **原话依据：** “后需我想trace有个agent，来找bug和报告到桌面”“就是一个trace app，能负责这个系统
  的错误和不对的地方，比如记忆召回质量，知识库如何提升和参数优化，还有刚才的这些工具失败和运行失败，
  给用户报告原因，形成报告”“这样做我们系统就能自我优化”“Trace 的那个 APP 就可以选择任何一个对话
  记录，比如说选择当前我这个 Room 的对话记录，我就可以让它去排查”“工具调用哪些失败，上下文有哪些
  问题，还有任务分配有哪些问题，然后给出怎么改，因为它也可以去改”“这个流程有哪些是冗余的，分配不
  合理，导致浪费 token，反复打回”“做 Trace App 的时候，给那个 Agent 配套 Skill，让它知道怎么高效排查
  各种问题”。来源：当前任务，2026-08-28。


### 来源覆盖审计

| 原话主题 | 对应需求 | 处理结果 |
| --- | --- | --- |
| 项目文件夹原地展开对话文件，便于查找并直观看状态/进度；只作 OS 显示 | UR-171 | 固定为虚拟投影，不写 Finder/Git、不复制 transcript、不改变 owner |
| 每轮一张可滚动折叠行星表、行原地更新、点击打开对应行星 Session、禁止多路刷屏 | UR-170, UR-172 | 收敛 Room 默认主视图；完整细节仍回到同一 Partner Session |
| 行星相互 @、分派、交接、复核、回执形成引力；图要像 Workflow/Coze 一样清楚 | UR-173 | 只投影权威事件并支持边/节点回溯，失败不冒充成功 |
| Trace/Eval 做通全系统，成为垂直 Agent 应用、RAG 与记忆检测的基础 | UR-166–UR-169, UR-174 | 从领域特例提升为公共 envelope、producer、持久化、UI 与 Eval 合同 |
| Trace Agent App 选择 Session/Room，诊断 Tool/上下文/分工/返工/token/Memory/RAG 并报告到桌面 | UR-180 | 消费公共 Trace/Eval，精确回跳 run/span/文件；候选修复先经沙箱重放与前后 Eval |
| Agent 自建垂直应用并在沙盒内自测、自查 Trace、自评；sgg/掌柜问数/RAG 示例 | UR-176 | 固定平台闭环与安全/promotion 边界；示例准确路径仍需事实收敛 |
| 沙箱作为插件，并用于面试展示 | UR-178 | 固定为 Pi Package Connector；核心保留执行、Stop、Trace/Eval 与持久化权威，不建立第二套 loader |
| 网页介绍模型总找错每个功能的真实前端 | UR-179 | 固定 source map、selection/build evidence、排除项和漂移检查；找不到链路只能标 unverified |
| 岛屿与设置美术慢慢尝试，不把文件夹误解为项目/Room 语义迁移 | UR-175 | 作为 P2 视觉探索，保持现有设置与数据权威 |
| 右上角第二个协同模式打开所有 Runtime 运行中行星 | UR-156, UR-177 | 明确显式入口、全量集合与超过五个的验收，拒绝固定 cap/启用子集 |
| 从头重写、所有页面/侧边栏、保留功能、消息流与结果 | UR-001, UR-003, UR-009 | 合并重复强调，所有独立约束保留 |
| 单一 Agent 入口、选择 Session/Room | UR-002 | 当前修正；旧“两个顶层 App”仅导航层被取代 |
| Room 多窗口、平等通信、Workflow、消息/loop、审批、最终答复 | UR-004 | 合并为完整 Room 用户流程 |
| Tutti 迁移、性能、可拆卸、旧前端切换 | UR-005 | 明确参考边界与回退要求 |
| ChromeOS、OS 感、三主题、右键/框选、动效、卡顿 | UR-006, UR-007 | 拆成系统交互与运动系统 |
| 内置 Browser 全权控制、无插件/中间层；Files/Terminal | UR-008, UR-009 | 明确直接控制与授权边界 |
| App 清单、输入法 App、Package 作为 App | UR-009 | 保留完整能力地图 |
| 文档先行、上下文引用、同步、原话与真实需求 | UR-010 | 升级为无损双向追溯规则 |
| 只显示必要信息，不显示愿景/内部结论 | UR-011 | 保留明确反例 |
| GPT Image 2、用户代生图、禁止装包、壁纸非优先 | UR-012 | 明确最后执行与工具边界 |
| 安装/卸载、自举、Pi 0.84、真实 Session/Room 验收 | UR-013 | 汇总为最终交付门槛 |
| Subagent 批量并发、后台工具、非阻塞推进、事件响应式聚合 | UR-014 | 新增控制需求，规范子 Agent 编排机制 |
| Tutti 对应功能直接迁移、空白 Browser、真实 Terminal、subagent 侧栏、Room 卫星窗与上下文传递动画 | UR-015 | 最新修正；功能和交互直接迁移，但 PAW Runtime/Room 权威不迁移 |
| Tutti 式 Agent 主工作面、新建/恢复入口、逐项消息与 Tool 时间线、先跑通 Session | UR-016 | 最新执行优先级；替换当前窄聊天布局和有缺陷的入口 |
| 修复被 Gemini 改乱的前端、先锁定 Tutti/HTML 单一基线、主题延后、composer 状态流光 | UR-017 | 当前收敛策略；路径级修正，不整树回滚 |
| Zoom 画布、窗口缩放/平移/拖动/resize、主窗周边伙伴小窗、消息与上下文公开流向 | UR-018 | 核心 OS 交互；先迁移 Tutti 窗口机制，再接 PAW 权威事件 |
| 老前端保持可用回退、新 PAWOS 不抢救 Gemini 形态、按功能逐步迁移 | UR-019 | 最新迁移策略；每个真实纵向切片验收后再前进 |
| Tutti workbench 作为 App 框架、停止 ChromeOS 式自研、先跑通后集中最小验证 | UR-020 | 最新实现节奏；保留既有测试，不为每个小迁移步骤扩张测试矩阵 |
| ChromeOS/Ash 统一 OS 外壳、Tutti 负责 Agent/Browser/Terminal App 内部 | UR-021 | 最新框架修正；取代 UR-020 的整壳选择，保留其验证节奏 |
| 受管 Chromium + 本机 CDP、无需扩展、控制与可见页面必须是同一 target、iframe 退出最终路径 | UR-022 | Browser 架构选择；原生窗口先跑通，同窗最终接真实 Chromium View |
| Room 需求/问题/答复/plan/文档/上下文按真实 FlowPacket 网状流转 | UR-023 | 最新 Room 动效合同；动画投影权威 dispatch/peer/WorkItem/ContextRef/receipt |
| 受管 Browser 保留原生历史、登录态与 Cookie，不另造第二层浏览历史 | UR-024 | 固定 Chromium Profile；原生 History 是唯一用户浏览历史 |
| 所有 App 保持干净，不把设计/架构/协议写入界面；Browser 只像浏览器 | UR-025 | 最新全局界面修正；删除解释型徽章、状态条、空白页技术错误和过度面板 |
| macOS 原生标题栏并入 PAWOS 状态栏、保留同一行窗口按钮 | UR-026 | 使用 full-size content titlebar，消除双顶栏 |
| 删除“澄”和角色设定；Agent 对齐 Tutti 的模型、会话设置与用户快捷提示词 | UR-027 | 角色字段仅作 Runtime 迁移兼容，不再进入 PAWOS UI |
| 主管 Agent 逐项负责、多个执行/验证 Agent、双重 verifying、subagent 批量并发、fresh/new 与 fork 按任务选择 | UR-028 | 固定工作闭环与责任合同；Skill 仍是按需方法，不是第二 Runtime |
| 每个 App 从头重做或直接迁移 Tutti 对应功能；删除假按钮、假搜索、宣传式桌面和角色开场 | UR-029 | 当前只显示真实对象、状态和已接通操作 |
| Agent 设置是独立功能；持久化模型/推理/权限默认值和用户快捷提示词；Composer 只改当前 Session | UR-030 | Settings 与 Composer 共享真实偏好和提示词数据，不恢复角色设置 |
| Agent 工作面直接搬 Tutti；小窗口优先并支持四五个伙伴窗同时可读 | UR-031 | 容器查询收拢侧栏/检查器/次要信息，保留消息、工具与 Composer |
| Blueprint 统一为清楚可辨的蓝色 App 表面，保留其他主题，网页内容不强制染色 | UR-032 | 删除 Agent 灰黑私有覆盖，统一使用系统主题变量 |
| Blueprint 采用 PAW OS · Blueprint Precision v3 浅蓝工程图风格 | UR-033 | 淡蓝网格画布、白蓝面板、清晰描边、克制圆角与最少毛玻璃 |
| Blueprint Precision 所有组件表面使用直角，只有窗口灯与状态点保留圆形 | UR-034 | 主题级清零圆角，保留必要圆形语义控件 |
| Composer 环绕流光导致窗口抽搐 | UR-035 | 删除无限 filter 动画，改为静态聚焦描边 |
| 模型切换与权限批准参考 GPT 分层菜单 | UR-036 | 自绘模型/推理与权限策略弹出菜单，消费真实 Session 参数 |
| Blueprint 与 P5 构图结合，避免过素但不铺满装饰 | UR-037 | 蓝图秩序上加入不对称层叠、斜切强调和一次性动效 |
| Mock/Preview 不算 Browser 与 Terminal 实现 | UR-038 | 接真实 PTY 与同 target 受管 Chromium 后才验收 |
| P4 蓝色取代 P5 视觉命名 | UR-039 | 已由 UR-049 取代，仅保留为修正历史 |
| 删除快捷提示词，Composer 只保留一处 Session/Room 单聊群聊选择 | UR-040 | 顶部重复选择器删除，底栏切换真实创建类型 |
| P4 蓝使用完整配套色系而非单一浅蓝 | UR-041 | 已由 UR-049 取代，仅保留“不能单色铺满”的约束 |
| 新建、Session、Room 统一为一个 Tutti 式 Composer | UR-042 | 同一骨架与布局；仅按上下文替换真实控件，始终停靠消息流底部 |
| Tutti 三段式 Agent 工作台、PAW 数据与最新主题皮肤 | UR-043, UR-049 | 入口栏/会话栏/内容区/单一 Composer；窄窗优先内容与输入 |
| 模型弹层、权限、Session/Room 与底栏互相叠压 | UR-044 | 锚定菜单、碰撞关闭、语义折叠；禁止竖排和永久覆盖 |
| 旧 UI 模型分层菜单比当前原生下拉正常 | UR-045 | 迁移 Provider 分组、推理子层与独立滚动，不再使用悬空表单 |
| 权限菜单缺少全自动 | UR-046 | 恢复真实 `full_trust`，提交明确确认并要求工作目录 |
| 会话侧栏默认隐藏、交互逐项学习 Tutti | UR-047 | 覆盖式会话抽屉；逐项迁移菜单、Composer、滚动与选择行为 |
| 菜单框错位、蓝色不是单一颜色 | UR-048, UR-049 | 每个菜单锚定对应按钮；用完整 P3R 配套色系建立层级 |
| 最终配色说错，改为 P3R | UR-049 | 已由 UR-050 取代，仅保留避免单色和高对比层级约束 |
| 主方向采用明日方舟式工业信息 UI | UR-050 | 白/冷灰/深炭/青/黄分层，保留 PAWOS 身份与真实内容 |
| 明日方舟不是暗色主题 | UR-051 | 白/浅灰/明亮青主导；深炭仅作局部导航和结构色 |
| 高级感来自大量动画与图片/视频 | UR-052 | 原创媒体主视觉叠加遮罩/切片/状态运动；数据面保持稳定并支持减弱动态效果 |
| 艺术感、大众审美、名家风格的动态背景 | UR-053 | 原创康定斯基式几何抽象主视觉；分层低速运动，工作控件保持静止 |
| Room 本体采用主窗周围真实卫星窗口 | UR-054 | 伙伴作为独立 Agent 窗口；跨窗消息动画与主 Room 账本来自同一权威事件 |
| 生图本身不会动，不能冒充动态背景 | UR-055 | 静态原创素材由多层 transform/opacity 运动系统驱动；工作表面不动 |
| 卫星窗口只显示伙伴对话内容 | UR-056 | 删除卫星窗内部二级头、上下文条和 Composer，把空间全部交给消息时间线 |
| 消息流转和特效需要重点优化 | UR-057 | 真实事件驱动的源窗、定向光路、消息包和目标到达反馈，单次播放并可减弱动态效果 |
| 一些侧栏对象也可以成为卫星窗口，例如 Session subagent | UR-058 | subagent 运行树可弹出独立消息/工具进度卫星窗，主 Session 不被侧栏挤压 |
| 每个 App 都要像 Agent App 一样细细打磨 | UR-059 | 每个 App 逐一完成真实纵向切片、窄窗/滚动/菜单/动效细节与回退边界 |
| Composition 8 静止接近原画、矢量不要堆叠 | UR-060 | 单一原画底图 + 稀疏 outline-only 特效；去掉重复大形体，分组可复用 |
| EgoNight/ego-lite 直接接入并替换原有 Browser 技能和插件工具 | UR-069 | 复用 PAW 受管 Chromium；接入开源 ego-browser 控制内核，删除已证明无消费者的重复链路，不安装第二个浏览器 |
| 人可操作同一 Browser；Ego/Agent 行为与轨迹必须可见 | UR-070 | Browser 页面与真实 command trace 并存；直接执行但不成为后台黑盒，可投射到 Session/Room 卫星窗口 |
| 每个当前对话直接切换到该对话的完整行为轨迹 | UR-071 | Agent Session 内同级“对话 / 对话轨迹”切换；不新增 App 或第二次 Session 选择 |
| App 无法关闭、Terminal 多实例关不掉；方形主题窗口灯仍为圆形 | UR-072 | 修复窗口 authority 生命周期；逐实例关闭并将默认主题交通灯改为方形 |
| 参考 Tutti 提供可介绍并按自然语言改造整个系统的自举 Skill | UR-073 | 先审计现有包，再迁移或创建最小原生 Pi Package/Skill，保留校验与安装回执 |
| Room 主窗过载、重复栏、次要信息应进入卫星窗，窗口要可拖动且背景有流动层 | UR-074 | 主窗对话优先；Flow/执行/进度/治理/文件/子 Agent 由 desktop authority 开卫星窗；前台拖动与动效仍待验收 |
| Agent 头像造成拥挤，要求彻底去掉 | UR-075 | 去除头像和头像空列，保留文本、状态与语义 trace；各 App 仍需逐项前台检查 |
| 卫星窗不能是玩具摘要，须显示真实 Pi 上下文并有 Codex/Tutti 运行动画 | UR-076 | 已接真实 projection/console 的代码路径；四窗实时上下文、动画、背景恢复和拖动仍待前台验收 |
| 新输入后旧失败/重试不能继续存在 | UR-077 | AgentTimeline 已限制旧回合失败操作；仍需补充迟到事件/重试回归矩阵 |
| 点击切换和发送反应太慢，需达到 Pi/Tutti 的即时感 | UR-078 | 已有 fast-path 与局部回归；完整交互延迟、背景动效和 installed foreground 仍未关闭 |
| Browser 必须是可用的完整同窗浏览器，框体不透明 | UR-079 | Ego/受管 Chromium/trace 单栈已接；当前截图交互是过渡形态，原生同窗 Browser 仍为开放验收边界 |
| 对话轨迹是既有真实 trace，不复制成原文聊天 | UR-080 | 继续使用 PawConversationTrace 与真实 reducer/Browser/Pi 事件；需做真实 Session/Room 前台确认 |
| Composition 8 用 Image 2 原画底图、全屏 cover、稀疏独立可动矢量 | UR-081 | 当前底图/两组 SVG 代码路径在位；最终视觉和静止/音乐律动验收未关闭 |
| structured_output schema 错误、token budget 和子 agent 失败必须可恢复 | UR-082 | Provider 前置 schema validator 与聚焦回归已在当前源码；token budget/失败界面与真实恢复仍待集中验收 |
| 所有 App 逐项接通后再统一测试，不能只完成 Agent 或保留网页旧页 | UR-083 | 作为本次 handoff 的总门槛；未宣称完成，等待统一集中验收 |
| Tutti/EgoLite/Codexx 成熟源码可直接迁移，不要防御性过度设计 | UR-084 | 采用纵向切片加薄 PAW 适配；宿主能力差异仍须真实解决 |
| Memory 作为第二大脑并提供真实可保存的记忆偏好页 | UR-089 | 在现有 Memory App 中增加同权威数据源的偏好页面，不使用前端假开关 |
| 顶部栏窗口控件切穿 PAWOS 品牌、Browser 标题失衡 | UR-090 | 窗口控制、品牌与当前 App 标题分槽布局；窄窗有序收起而不重叠 |
| App 顶部不要窗口标题栏与内部 App/标签栏重复两层 | UR-091 | Browser 将真实标签并入窗口 chrome；其他 App 删除同名重复 header |
| 全局 OS 动画特效缺失，每一个 App 都要改 | UR-092 | 统一状态驱动 motion tokens；逐 App 覆盖真实关键状态与 reduced-motion |
| Browser 外观像旧式前端，ChromeOS 应有丰富动效 | UR-093 | 重做现代 Browser chrome/History/Settings surface，并为真实状态增加快速连续动效 |
| 卫星窗调出后弱化背景、强化信息流转并增加窗口特效 | UR-094 | 真实 satellite 生命周期进入协作聚焦态；FlowPacket 驱动方向与一次性到达反馈 |
| 很多 Feature 仍只是旧网页套窗，字体不可读，每个 App 都要真正精修 | UR-095 | 逐 App 删除重复 shell、重排核心任务、让语义字号真实覆盖并做安装态逐页验收 |
| 主对话关注点错误，卫星窗口重复标题、遮挡且难看 | UR-096 | 主窗对话优先；卫星直接显示对应真实内容并按主次布局、聚焦和流转 |
| 卫星不是普通多窗口，而是铺满并专注当前 Room 的模式 | UR-097 | 明确 Room Focus Mode；主对话居中、辅助信息轨铺满、其他桌面对象退场且可恢复 |
| Pi 调后台 shell/bash 或 Browser 时提供真实执行视图 | UR-098 | Tool 事件按 runId/targetId 复用 Terminal/Process 投影或 Browser 标签并持续更新；后台 Bash 默认显隐由 UR-130 修正 |
| Terminal 优先使用已安装 Ghostty，未安装才用系统默认 | UR-099 | 已被 UR-105 取代；仅保留历史原话收据 |
| 全量图标与当前视觉风格不一致 | UR-100 | 重制 11 个原创 PAWOS App 身份 SVG，并统一接入桌面、Dock、Launchpad、标题栏和 App 内身份位 |
| UI 打磨参考 Impeccable、Anthropic Frontend Design 与 Taste Skill | UR-101 | 以 Impeccable 为主线，吸收 anti-slop 与构图差异性；排除不适合桌面产品的营销页模式 |
| Project 至 Files 九个核心 App 需要逐个设计和审美检查 | UR-102 | 九份独立 App 验收凭据；逐项检查真实状态、宽窄窗、字体、层级、交互、动效与旧网页壳残留 |
| 当前统一折角底板图标被明确判定太丑 | UR-103 | 整体废弃并改为 11 个独立几何剪影；先做四尺寸真实图标墙肉眼迭代，再接入与测试 |
| App 颜色单调且不美，前端不应被 Composition 8 绑架 | UR-104 | 美感优先；逐 App 建立独立色彩/材质层级，壁纸不再约束图标和界面语言 |
| Terminal 不能打开新应用，并明确不要 Ghostty | UR-105 | 统一为 PAWOS 内嵌 PTY/xterm；不得自动启动 Ghostty 或 Terminal.app |
| 提供一版 Composition OS zip 并要求安装看看 | UR-106 | 作为不覆盖正式版的 Preview 候选安装；附件文档不自动改写现行愿景，待真实视觉判断后再决定是否晋升 |
| 提供第二个 Composition OS 包 | UR-107 | 只接入相对第一包新增的逐 App 样式，备份第一版 Preview 后覆盖 Preview 通道，正式版与 Runtime 不动 |
| 14 个网页模型分包要求安装整理、尝试迁移 | UR-108 | 只迁移兼容视觉增量；HTML/PNG/静态状态不覆盖真实 owner |
| 当前页面不精致、错行、乱位、字体和 App 适配失败 | UR-109 | 新增窗口级排版、动态内容、宽窄窗与安装态逐页验收合同 |
| 网页模型不知道各 App 功能、需求没对齐 | UR-110 | 设计顺序改为功能/authority/状态先行，不再先做统一皮肤 |
| 候选错误地按 12 App 设计 | UR-111 | 固定 11 顶层 App；Room 回归 Agent 内协作模式 |
| 根据整段对话更新需求并产出下一轮 MD | UR-112 | 单文件优先写愿景、功能接口、候选偏差和逐 App 验收规则 |
| 静态截图和作者 QA 不能证明功能完成 | UR-113 | 分开报告视觉、源码、测试、安装和真实前台证据 |
| 三主题先不推进 | UR-114 | 当前只跑通默认单主题；主题变体与切换验收推迟 |
| 当前深色方向与对话定稿不符 | UR-115 | 默认单主题改为明亮、轻透、青春鲜活；深色仅留功能性局部 |
| 真实数据包必须包含多人对话等可直接渲染场景 | UR-116 | 补齐四人 Room、工具/审批、WorkItem、局部失败、恢复、Root 收束与卫星派生投影，不再只给孤立路由字段 |
| 当前真实消息流没有按最终方向完成，网页模型图是轨迹页 | UR-117 | 实际对话改为输入/输出分离且保留真实交错顺序；Agent 轨迹独立按 Turn/事件展示，不复制正文 |
| 十二个网页模型迁移面必须逐包读完；全彩图标和分包对话不能漏装 | UR-118 | Shell 三包合并为一面，其余逐面迁入真实 owner；保留 11 App 注册表并拒绝 mock backend/seed |
| 完整迁移不能只是打包、盘点或 CSS 适配 | UR-119 | 候选 IA/DOM/交互/响应式/动效进入生产 owner；两轴与安装态均未通过前保持 partial |
| 新版前端直接接生产后端并作为唯一主线 | UR-120 | 全部页面与动作接 typed routes/reducer/SSE/native owner；不建立 mock-first 平行 UI |
| Room Focus 仍是旧卡片拼窗且泄露原始回执 | UR-121 | 中央对话主叙事、卫星结构化摘要、次级流转 ledger、宽窄窗不遮挡不竖排 |
| Agent 工具栏重复、空面板挤压对话 | UR-122 | 工具按需披露；同一动作只保留一个 owner 和入口 |
| Room 工具重复且遮挡对话 | UR-123 | 收敛为一个按需协作工作区，不复制伙伴动作或原始回执 |
| 网页模型缺少生产 Session/Room 真实采样 | UR-124 | 单列隐私安全的生产数据边界；fixtures/demo 不冒充 Runtime 事实 |
| 网页模型需要完整可编辑 ZIP | UR-125 | 保留真实源码树、权威文档与构建配置，排除依赖、产物和机器数据 |
| 直接嵌入 EgoLite、补齐 Ego 特效 | UR-126 | 同一 Electron guest 迁移 Ego 可观察体验并复用开源 ego-browser 控制内核 |
| Browser 输入框异常、App 落在 Dock 后面 | UR-127 | 输入控件单一 owner；普通窗口层级高于 Dock，并做安装态几何验收 |
| Agent 连到共享 Profile 的陈旧端口 | UR-128 | 当前 Electron PID/listener 是 CDP authority；无可验证端口时 fail closed |
| 真实完成一个任务，例如查看今天新闻 | UR-129 | 同一可见 guest 完成真实读取与 Task Space 生命周期；Ego Host 跟随当前 CDP |
| 命令行默认不弹出，只有用户专门查看后台 Bash 才弹出 | UR-130 | 后台进程默认静默并保留紧凑状态；显式查看才打开同一 runId 的 PAWOS 内嵌投影，不重跑、不抢焦点 |
| 右键功能一键关闭所有窗口 | UR-131 | App/Dock/窗口/桌面右键提供范围清楚的关闭全部；只移除投影，不停止 Runtime 工作 |
| 对话能力加入记忆召回、Knowledge/Agent RAG、压缩后继续召回 | UR-133 | 复用既有权威能力，提供可单独关闭的对话能力，不建立第二套 Runtime/RAG |
| Memory/RAG 必须在对话、思考、工具和上下文装配中显示并跳来源 | UR-134 | 使用真实 trace/收据，支持来源与 Session/trace 双向跳转 |
| 模型弹层过大，模型与强度分别选择 | UR-135 | 分层紧凑选择；第三种组合含义未明确，不臆造 |
| 思考/工具显示耗时与 token，Context Usage 拆真实组成 | UR-136 | 只显示权威值或显式估算/未知；工具内容默认收起 |
| 对话框/错误框太重，星球动效粗糙，完成后仍显示进行中 | UR-137 | 收紧视觉层级并以 terminal/durable 快照正确收敛状态 |
| 流式输出闪烁、抢滚动，长对话疑似丢历史 | UR-138 | 稳定增量、用户滚动优先、durable 历史不因投影/压缩消失 |
| 本地为主，远端 12 点前提交择优吸收 | UR-139 | 逐项审查，不整体覆盖；12:00–13:00 边界保留歧义 |
| Memory 整理先给真实样例、显示进度并防重复点击 | UR-140 | 复用月历范围与同一后台 job，单飞 mutation、恢复进度和终态收据 |
| Room 伙伴数量可调、运行中持续 steer，相关修订不影响无关验收 | UR-141 | Facilitator 选择既有 return/revise 或普通新增；代码只校验 ID/revision/权限，人数 1–8 |
| MLX 与输入法预测从 Input Studio 消失 | UR-142 | 恢复真实字段并并列展示保存态、生效态、profile clamp 与本机模型健康 |
| 最终回复已出现但仍显示思考中 | UR-143 | terminal 事件与 durable snapshot 幂等收敛，不让调试/召回投影阻塞终态 |
| Memory Recall 默认关闭、由 Agent 判断调用、每压缩周期可限次 | UR-144 | 独立能力开关与设置；启用后显式 Tool 调用，收据默认折叠 |
| Context Usage 需要系统提示词、消息、工具、压缩等具体 K 数 | UR-145 | 精确值与估算分开，保留未知 remainder，不用单一总红条代替分层 |
| 可见伙伴全部换成行星并清理 Agent 编号/旧角色混用 | UR-146 | 行星名是稳定主身份，责任是次级标签，内部 participant ID 不改写 |
| 模型和推理强度仍共用图标/布局相撞 | UR-147 | 不同图标、入口、弹层和命中区，窄窗也不重叠 |
| Settings 分别设置行星与卫星模型 | UR-148 | 分开保存 visible Partner 与 private Tool Agent 默认模型/强度 |
| Room 仍是另一套方框风格，协作网关系与文字混乱 | UR-149 | 中央对话复用 Session 语法；卫星渐进披露；真实关系图稳定不重叠 |
| 从当前仓库自主选择最值得展示的能力 | UR-150 | 以 owning source、新鲜证据、数据来源和限制选择，不由旧截图或文案决定 |
| 自主设计 Demo 剧本并搭建录制链路 | UR-151 | 公开 fixture 与真实 Runtime 分轨；脚本化截图/视频、失败恢复和清理 |
| 补充 README 宣传与截图 | UR-152 | 每项声明和图片标注 revision、来源与 E1–E6 证据边界，保留发布限制 |
| Steer/插入消息错位、提交后看不到输入、跳到最新闪烁 | UR-153 | 同一权威 Turn 顺序、用户回执与单次显式滚动，不让流式更新重排 |
| Tool 失败后后台继续、计数口径错误、Tool 阶段仍显示 t/s | UR-154 | 同 runId 后台投影；调用/种类/事件分开；当前模型吞吐不跨调用复用 |
| 图片粘贴失效、模型与推理控件碰撞 | UR-155 | 媒体导入保留草稿；单一组合入口内语义分层且任何宽度不遮挡 |
| Room/Session 同一 UI、4 列并行、行星/私有 subagent 卫星 | UR-156 | 普通 Session 组件复用；稳定分列；协作态势唤起全部运行中行星，私有 subagent 仍只在其 Session 内称为卫星 |
| 协作模式自动弹出全部运行中行星 | UR-156 | 最新修正；以 Runtime active Partner 集合为准，不只恢复手动启用子集 |
| 新 Room 先问是否开始、确认后全部无需逐 Tool 审批 | UR-157 | 一次性 start gate 与默认 room_unrestricted 分离，安全/Stop/审计仍保留 |
| Room 只是提示词/Session 组合，平时 Session 不注入 | UR-158 | 新 Room Partner 一次 bootstrap，后续只送增量，普通 Session 零 Room prompt |
| 持续报告完成/当前/下一步、需求文档勾选与结果 | UR-159 | 四条证据轴分离；WorkDocument 可选且不阻断真实结果交付 |
| Stop 不收敛、未停止对象不清楚 | UR-160 | stopping 单向收敛到 stopped/partial_stop，并列出精确 pending |
| 协作关系改成 DAG、失败原因要可见 | UR-161 | 只从成功事件画边；失败尝试进入阻塞披露而非成功关系 |
| 桌面显示哪些对话正在执行以及正在做什么 | UR-162 | Runtime-owned 当前工作投影；关闭/最小化窗口不等于停止执行 |
| 更新/安装 Squirrel、Pi Runtime、MLX、前端并交付 main | UR-163 | 当前源码开发安装、组件级回退与独立 Git 落地边界 |
| Browser 不保留 Swift fallback，只发布 Electron/Ego/CDP | UR-163 | 最新修正；回退仅使用历史 Electron 构建/commit/备份 |
| 清理 Runtime Skill 来源说明、Ego 对话并整体审计 | UR-164 | 运行时上下文只保留独有可执行方法、安全与不重复反例 |
| Memory 整理永久转圈、重启后失效 | UR-165 | 旧 job 明确中断/可恢复并停止轮询，不伪造完成 |
| Memory 整理输入、工具、阶段和耗时 Trace | UR-166 | 显式详情加载公开对话与有界执行证据，列表仅元数据 |
| 对话 Memory/Knowledge 命中、embedding/BM25/图多跳与注入原因 | UR-167 | 同一 Trace 语法、不同 authority、逐阶段耗时和 Turn 双向链接 |
| 周期 AI Judge、准确率/召回率/F1 与依据检查，默认 Luna Max | UR-168 | 标注集真实指标与无标注 AI 估计严格分层，报告只读不自动改系统 |
| 输入法生成需要更多近期输入/屏幕语义、预算设置、Trace/Eval 与最近输出结果 | UR-169 | 真实 AX/近期输入装配与 requested/effective 收据；显式 `input_generation` Eval 样本 |
| Room 每轮行星任务表、一个 Room 输入、行星 Session 详情与单窗口框 | UR-170 | 一轮一表、按行星原地更新；完整行星 Session 负责 Trace/debug，输入回到 Room `@伙伴` |
| Room 主窗口必须重新设计，不能只做弹出的行星窗口 | UR-170 | 主窗/行星 Session 分工与 round sheet 先评审后落地；现有四列不是最终验收 |

**覆盖结论：** 当前任务中已取得的全部 PAWOS 产品/文档要求，以及指定旧任务
中本文件所摘录的相关用户消息，均已映射到 `UR-001`–`UR-195`；重复强调没有
被当作新功能，但保留为优先级证据。环境状态、附件包装、Agent 回复和“继续/
设置 goal”“并行修复 bug”“你干活的子agent用sol”等协调动作不作为产品
需求；它们作为本次执行约束处理。只有图片而没有文字的消息归为附件参考，映射
到相邻文字要求，不从图片内容推导新的用户指令。旧任务没有在本轮全文导出的
非相关消息不在“完整覆盖”声明范围内。

## 继续阅读 / 编辑

- 下一份：[UR-181](PAWOS_REQUIREMENTS_181_181.md)
- 原话与来源覆盖：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
