# 星空、项目星系、Browser 与性能续接

由继续任务 `01a071a1-a095-7e73-a2d5-e97cfefaa09f` 主 Agent 维护，2026-09-05 开始，最新材质与运动修正延续至 09-06 上午。完整目标仍是先优化 OS，再逐 App 检查交互、UI 和功能；本记录不关闭全 OS 要求。

直接来源分卷：[UR-267–269](requirements/PAWOS_REQUIREMENTS_267_269.md)、[UR-270](requirements/PAWOS_REQUIREMENTS_270_270.md)、[UR-271](requirements/PAWOS_REQUIREMENTS_271_271.md)、[UR-272–274](requirements/PAWOS_REQUIREMENTS_272_274.md)、[UR-275–277](requirements/PAWOS_REQUIREMENTS_275_277.md)。最新修正明确拒绝塑料球，要求银河中心不画成太阳，并补上自转与轨道模拟。用户已两次否定材质；最新版本的用户视觉满意度尚未确认。

## 当前可见行为

打开桌面项目文件夹（双击、Enter 或空格）直接进入全视口 3D 星系。行星从中心依次旋出；点击球体或它的文字标签选择真实 Session/Room，详情展示真实状态、最近公开进度和已有 Room 任务完成数。项目星核及顶栏“项目 docs”打开文档。文字列表保留在次级按钮，返回桌面恢复文件夹焦点。

普通 Session 没有总任务数时不生成百分比。入口旋出是一次导航动画，不表示所有对话正在运行。最新 UR-277 显式要求物理运动，因此自转/公转与 Runtime busy 分离；真实状态仍由文字和状态色表示。暂停和 0.25× / 1× / 4× 倍率仅控制场景模拟。

### 为什么重做渲染器

第一版采用圆形图片和网格排布，用户明确拒绝；随后提议复用旧 `StarfieldStage`，用户再次要求重做。最终项目星系是独立实现：

- [PawProjectGalaxy.tsx](../../src/paw-os/shell/PawProjectGalaxy.tsx) 管理选择、分页、搜索和 docs 披露。
- [PawProjectGalaxyScene.tsx](../../src/paw-os/shell/PawProjectGalaxyScene.tsx) 惰性创建 WebGL，并提供同一真实身份的键盘标签和销毁边界。
- [project-galaxy-stage.ts](../../src/paw-os/shell/project-galaxy-stage.ts) 管理新的相机、球体、光照、轨道、粒子和资源。
- [project-galaxy-surfaces.ts](../../src/paw-os/shell/project-galaxy-surfaces.ts) 在真实球体上加载本地天体表面资料；月面配高度、地球配独立云层，星环投射/接收阴影。素材来源和修改边界见 [ATTRIBUTION](../../public/paw-media/project-galaxy/ATTRIBUTION.md)。不再使用被拒绝的球面噪声和彩色条纹材质。
- [project-galaxy-volume.ts](../../src/paw-os/shell/project-galaxy-volume.ts) 用三维密度场、视线步进、前向发光/吸收合成银河旋臂与暗尘；不再堆叠模糊点精灵当星云。中央是弥散星核，没有可见太阳 Mesh。
- [project-galaxy-shaders.ts](../../src/paw-os/shell/project-galaxy-shaders.ts) 保留薄大气与批量星点。旧 Starfield 的表面资产可复用，其视觉渲染器没有复用。
- [project-galaxy-physics.ts](../../src/paw-os/shell/project-galaxy-physics.ts) 积分倾斜、非圆测试轨道；[project-galaxy-labels.ts](../../src/paw-os/shell/project-galaxy-labels.ts) 在投影后避让标注，必要时加引线。
- [project-galaxy-model.ts](../../src/paw-os/shell/project-galaxy-model.ts) 保留实际 Session/Room ID，只用稳定身份决定材质和空间位置。
- [project-galaxy-entrance.ts](../../src/paw-os/shell/project-galaxy-entrance.ts) 定义一次旋出；减少动效直接落到最终轨道。

本轮对旧 `StarfieldStage` 和 `Starfield3D` 的试接修改已撤回；原 Session/Room 星场及已有消费者保留。新实现复用 Three.js 基础库与有署名的本地表面图，没有沿用旧视觉场景。

### 项目 docs 的真实边界

[PawProjectDocuments.tsx](../../src/paw-os/shell/PawProjectDocuments.tsx) 通过项目已有且根目录匹配的 Session 读取工作区；必要时匹配同一真实 Room 的 participant Session，不把桌面分组键当 Project/Session ID。根目录展示实际 md/mdx/txt/rst 文档和实际存在的 docs/doc/documentation 目录，子目录由列表返回值导航，预览上限 64 KiB，完整阅读交给既有 Files。

未绑定文件夹提供打开原对话选择工作区的动作。它不会猜路径或调用文档 RPC。失败支持重试；换目录、换项目、关闭时取消旧请求。项目设置不是工作区绑定的唯一 owner。

### 性能边界

每页最多 12 个真实行星，Three.js 和文档组件按需加载。当前三个星点批次为 4,800 个盘面点、2,400 个核区点和 900 个远星；粒子数量不随历史 Session 总数增长。体积噪声为 64³ 单通道（256 KiB），步进质量为 48 / 40 / 32，表面图按场景缓存，关闭释放，迟到加载也释放。球体共享几何，状态更新保留原行星、轨道 BufferGeometry 和相机；搜索/分页不再重建 WebGL。没有逐帧 React setState 或逐星点 CPU 更新。

渲染最高约 30 帧/秒，DPR 上限 1.5，总像素预算 180 万；持续 CPU 慢帧或帧间隔延迟会降低分辨率和体积步数。隐藏或离屏取消连续渲染，隐藏 resize 延后 GPU setSize，减少动效和显式暂停按需绘制。关闭会断开观察器和事件、取消帧、释放材质/几何/纹理/renderer/context。星系打开时，底层 Stellar 壁纸也暂停，避免两层宇宙同时绘制。

这些是有界实现与实际暂停/卸载证据，不是整机 FPS、功耗或全 OS 压力测试结果。生产构建仍提示部分已有图形、校验和代码语言块超过 500 kB。

## 思考星核偏心的原因与修复

用户最后的截图针对小型“思考中”指示器。`.agent-assistant-pending > span` 把行星根节点也当作文字容器，覆盖了 `inline-grid` 为 `inline-flex`，使核心移到左上角。

已在基础 Agent CSS、PAWOS 执行条 CSS 和 reasoning-feed 文字选择器中排除 `.paw-conv-planet`；星核自身用绝对位置固定到标记中心。浏览器中使用真实 pending 条结构和源码组件测得：20×20 px 标记的星核中心偏差约 `(-0.0142, -0.0142) px`，修复后根节点为 grid。旋臂和卫星仍分别使用 6 秒思考、2.4 秒工具周期；等待、完成、失败保持停止，后台/离屏/减少动效可暂停。

系统爪印同时已替换成静态带环行星与引导星，SVG、64/192/512 PNG 及 Electron 图标构建输入保持一致；这不修改通用输入法和 Squirrel 的身份资源。

## 桌面星空和暗色

[PawStellarBackdrop](../../src/paw-os/shell/PawStellarBackdrop.tsx) 复用 `PawWorkDirectoryProvider`，按真实新鲜 Session 状态投影后台 Agent 星球，没有第二套 Runtime 轮询。只有显式 parent Session 关系能画连线。同 Room 成员的归属冲突有确定处理，不能把其他 Room 的名称或 participant 偷渡进来。

壁纸粒子固定 96 个，窄屏 48 个。层间 transform、拖动/阅读/隐藏/减少动效暂停保留；固定 Stellar 桌面不再挂载仅被 CSS 隐藏的旧 `PawCompositionField`，其其他消费者保留。隐藏页面时目录内容仍在，但 freshness 清除，前台成功读取后恢复，防止旧 busy 瞬间点亮星球。

解除 PAWOS 的强制浅色，接回原 ThemeProvider 的 light/dark/system 和持久化偏好；Evolution Report 的独立浅色边界保留。修复了深色 Wayfinder 背板遮住星空、系统设置阅读区仍白色、行星球面高亮覆盖纹理和说明文字不清楚等实际可见问题。跨窗口 storage 同步不回写循环；清除偏好回到 system。

目录当前读取最近 100 条且排除 internal/subagent，因此并不代表全部后台内部 Session。本轮没有用真实同时运行的两个内部子 Agent 完成壁纸验收，不把布局样本或测试当成该项完成。

## 完整 Browser

HTTP 控制页面不能提供 Electron Guest 浏览器。原生历史和设置原本已有，本轮沿用唯一 Electron partition，并增加书签与真实下载记录入口；不会把 HTTP 页面伪装成完整原生 Browser。

新增 [browser-library.mjs](../../electron/browser-library.mjs) 和 [BrowserLibraryPanel](../../src/features/browser/BrowserLibraryPanel.tsx) 管理书签、下载及其更新。下载记录来自真实 `will-download / updated / done`，打开和定位以主进程持有的 DownloadItem 身份/路径为准；http(s) 书签拒绝凭据 URL。进度持久化合并为 1 秒写入，终态立即落盘，元数据失败不打断实际下载，用户另选 SaveAs 路径仍有效。

显式 Astra 复核补齐了五类失败：旧列表回包覆盖新事件、取消回包覆盖终态、已经完成却提示取消成功、临时读取保存路径失败丢失实际 SaveAs 路径、元数据记录缺失使活跃下载无法取消。主进程活跃 DownloadItem 映射保持取消权威。

原生窗口捕获遇到 ScreenCaptureKit `-3811`，未完成新的原生 Browser 前台书签/下载验收。当前安装 build 1429 没有被本任务更新；真实下载结果不能由 HTTP UI 或 mocked DownloadItem 推断。

## Runtime 和 Memory 收尾

只读现场证据显示 `/api/agent/runtime` 的 busy 投影可包含历史失败 turn，而列表和数据库对应 Session 已 idle。根因是在没有当前 client 时，观察性的 `queue_update` 会重新写入 `_states`、live turn/client/admission。

`rag_ime/pi_runtime_v2.py` 已使 queue 更新仅发布原事件，不重新打开历史状态，也不覆盖更新的 live turn 或承认保留的 prompt admission。三条回归先失败再修复，另保留 native steer/follow-up/error/abort 的覆盖。没有用该错误 busy 覆盖目录星球，也没有新增轮询。

Memory 的明确历史主题读取现在可包含 superseded 来源；普通当前目录仍排除它们，历史页面从合格原子重建，不复活已退休摘要。没有修改个人数据库。

观察时 Gateway/Pi 有活跃工作，其他任务还在做评测，因此本轮没有重启或安装 Runtime。旧进程可能保留已有的 stale 状态直到正常恢复。原大轨迹故障 Session 仍需同案验证；另一个 resident Session 的约 70 ms 成功轨迹只证明那个路径，不能代替原案。

## 09-06 上午：材质、银河与运动的当前检查

### 因果与修正

最初紫色边缘光、程序噪声和相同球形比例使行星像塑料；把天空换成大量模糊点又变成棉球。改成地表图片后用户仍明确拒绝，因此继续改变光照/阴影、体积星云和空间关系，没有把“已换图”当成完成。

当前月面使用 NASA SVS LROC 色图与 LOLA 高度预览，火星使用 NASA/JPL-Caltech 的 Viking/USGS 图；Earth/Jupiter/Saturn/Mercury 复用仓库有署名的 Solar System Scope 图。NASA 图并不意味着每种天体都采用原始测量或实测粗糙度。图像均为球面材质，几何、大气、云层和阴影由 3D 场景处理。前四个任务稳定分配不同表面，新增任务、状态更新、搜索和翻页不会给已有任务换身份。

物理采用无量纲、时间压缩的 Plummer 星核加有核对数晕，使用 kick-drift-kick Verlet 小步积分；每个导航天体有固定轴倾角与独立自转。轨道线由同一积分器预测，并在状态刷新时保留。银河旋臂使用稳定图案，盘面星点以不同角速度穿行；统计亮度增强表现臂内年轻恒星。此前直接按每个半径把整个密度场差速拖走，在持续运行时卷成同心环，已移除。这里没有实现自洽 N 体引力、流体星云、太阳系星历或真实尺寸比例。

模型参考：[galpy Plummer potential](https://docs.galpy.org/en/v1.7.2/_modules/galpy/potential/PlummerPotential.html)、[logarithmic halo](https://docs.galpy.org/en/v1.7.2/_modules/galpy/potential/LogarithmicHaloPotential.html)。旋臂与穿行恒星的概念参考 [NASA/JPL](https://www.jpl.nasa.gov/news/charting-the-milky-way-from-the-inside-out/)，其完整物理没有由本场景实现。

### 当前源码与前台证据

- 生命周期、物理和布局分别有先失败后修复的检查：搜索/分页额外创建 renderer，隐藏 resize/render，轨道资源重建，首次 docs 加载让整个地图挂起，以及近邻标注重叠。红测记录为 `/tmp/paw-galaxy-navigation-red-20260906.log`、`paw-galaxy-lifecycle-red-20260906.log`、`paw-galaxy-docs-loading-red-20260906.log`、`paw-galaxy-physics-red-20260906.log`、`paw-galaxy-labels-red-20260906.log`。
- 13 个相关文件 **161 项通过**，记录 `/tmp/paw-galaxy-photographic-final-tests-20260906.log`；独立补跑正确命名的 `PawWayfinderWork.test.tsx` **25 项通过**，记录 `/tmp/paw-galaxy-wayfinder-final-tests-20260906.log`。两次运行合计 14 个文件、186 项；最初命令写了不存在的 `PawWayfinder.test.tsx`，未把该参数误记成已执行。最后旋臂修正后 Stage/physics **6 项再通过**，不与 186 相加。
- 物理检查包括 20 模拟秒的倾斜圆轨道半径/轨道面、400 模拟秒的偏心轨道近心加速、能量漂移小于 1e-5、角动量保持及暂停零步进。材质检查覆盖缓存共享、失败不循环加载、关闭后的迟到加载释放。
- 最后旋臂修正后的 `VITE_CONTROL_TRANSPORT=http VITE_BUILD_CHANNEL=production pnpm run build --outDir output/stellar-build` 包含真实 `tsc -b`，已通过；记录 `/tmp/paw-galaxy-photographic-final-build-20260906.log`。此前 `GalaxyMotion.orbitRadPerS / spinRadPerS` 的陈旧下游引用与 Float32Array 推断错误均已修复。产物没有安装，Gateway/Pi 没有重启。已有共享大块提示仍在。
- 实际 Edge 页 `http://127.0.0.1:5183/?frontend=paw-os#/agent`，从桌面打开四任务文件夹。暂停前后各个标签 transform 保持不变，恢复/倍率来自界面操作；运行中采样无标注矩形相交。4× 连续播放至少 98 秒后旋臂仍保持银河形态，没有再次卷成密集同心环。Console 只保留此前启动与已修复 PCFSoftShadowMap 的旧记录，本次没有新 shader 错误。
- 实际三任务文件夹选择已有仓库工作区，读取并显示真实 PROJECT.md 完整预览；地图仍为 `ready=true`、Canvas=1、wallpaper paused=true。文档的首次惰性加载现在由局部 Suspense 承担，地图不再随其隐藏。无工作区的四任务文件夹显示“尚未绑定工作区”和原对话入口。返回后 Galaxy/Canvas=0、焦点回到“未绑定项目4 个文件”。
- 窄屏实际 CSS 视口约 354.5 px：Canvas 同宽、document scrollWidth=354、docs 面板 left=10/right≈344.5，无横向溢出；设备模拟已恢复。最后旋臂形态小改早于最终桌面实景，但晚于此次窄屏几何检查，未重做不受影响的同尺寸布局检查。
- 体积/阴影/标注版本的实际 31.01 秒运行采样：ScriptDuration 增量 0.983 秒、TaskDuration 增量 4.939 秒、LayoutDuration 增量 0.0079 秒，JS heap 约 61.1 MiB；当时画布 2089×861，在 180 万像素预算内。最后旋臂图案小改后未重做该性能采样。CDP Performance 测量已停用；数据不等同 GPU FPS、功耗、发布构建或全 OS 压测。
- 最终选择核对在界面暂停后完成，显示真实 Trace Session 的“就绪”和已保存公开进度；没有生成百分比。运动中的同一标签使自动化稳定性等待超时，暂停后的选择通过；不能把该自动化等待直接定性为人工点击失败。

当前源页可以查看，新视觉仍等待用户实际反馈；不把上述功能与资源检查称为用户已满意。

## 上一轮检查和实际页面证据（历史，不代替最新材质验收）

- 最后 10 个相关前端文件 **170/170 通过**（2026-09-05 23:58 启动）：Desktop、Backdrop、ProjectDocuments、ProjectGalaxy、ProjectGalaxyScene 生命周期、Wayfinder、纯模型、旋出、ConversationPlanetMark、ActivitySummary。命令前缀为 `pnpm exec vitest run --maxWorkers=1 --testTimeout=60000`；对应文件均在上述组件旁。
- 第一轮新星系检查发现了 `-0` 终态测试值和旧“默认选中第一颗行星”的测试假设；修正终态返回值和新版交互测试。Desktop 后加载 Galaxy 的单项检查需要超过测试框架默认 1 秒，改为明确 5 秒等待，原功能未加延时；实际桌面路径也单独通过。
- 前一轮主题、Browser、目录、标识和入口等 17 文件 **288/288 通过**，但该数字早于用户要求重做渲染器，不代替最新 170 项。
- Electron Browser library/host-config **28/28 通过**；Python queue 与 Memory 相关 **17/17 通过**。此前独立 Browser UI 36 项、执行动效 136 项为各自分支范围，有重叠，不能相加成一个全量总数。
- 当前生产 HTTP 构建：`VITE_CONTROL_TRANSPORT=http VITE_BUILD_CHANNEL=production pnpm run build --outDir output/stellar-build`，包含真正的 `tsc -b`。`tsc --noEmit` 在根 references 配置下不能代替 typecheck。产物声明 HTTP-only、排除其他 transport 和 preview fixtures。仅输出到忽略的本轮目录，未覆盖已安装 App。
- 新 Galaxy UI 与 Stage 分成独立惰性块，约 11.1 / 14.7 kB（未 gzip）；Three.js/OrbitControls 为另外的共享块，约 551.6 kB，不能在大小说明中省略。
- 实际源码桌面：打开真实“未绑定项目”直接进入星系，显示两个真实 Session，`renderer ready=true`，底层 wallpaper paused=true。返回后 Galaxy/Canvas 均为 0、焦点回到原文件夹、壁纸恢复。
- 实际授权项目的 docs 组件：读取 PROJECT.md，导航实际 docs 目录、子目录及面包屑，跳到 Files 后定位同一路径并完整渲染 115 行 Markdown。该页使用真实 Session 授权的已保存目录记录，属于组件/API 集成验证；不冒充主桌面已绑定文件夹或新的 native 安装。
- 重做后的窄屏检查实际 CSS 视口为 **355 px**（设备模拟宽 390，浏览器存在缩放）：document、canvas 均 355，无横向溢出；文档面板宽约 334.5，在视口内。减少动效切换得到 `data-motion=reduced`；设备和媒体模拟已恢复。
- Import boundaries、Route ownership、Project harness 已通过。需求状态检查作为结构核验另行记录，不能证明产品验收。

22:11 的较早全库运行结果为 279 文件、3156 测试，其中 12 文件/19 项失败。它与“读取项目需求与设计文档”等任务同时改写 App 源码和红测重叠；配置、Monitor、Voice 随后已经在单项隔离中通过。剩余全库 History/Lab/Workbench 等归属原任务，本任务没有据此改写其实现，也不声称全库全绿。

## 继续边界

所有已记录用户要求继续保留。当前结果是工作区源码、相关检查、生产构建和有界浏览器交互结果；没有 commit、push、安装、Runtime 重启或新增对外消息操作。原生 Browser 的完整前台路径、真实多后台内部 Agent、原大轨迹恢复和全 OS 逐 App 验收仍各需自己的证据。

本轮较早的继承模型解释已纠正：后续 Browser、主题、Runtime 三条复核通道创建时显式选择 `gpt-6-astra`，旧通道已停止。子 Agent 报告只是证据，以上集成和最终检查由主 Agent 负责。

## 2026-09-06 最新视觉回退与能力续接

用户选择电影感、允许抽象之后，又明确拒绝新暗色烟雾桌面并要求换回。已恢复前一版桌面绘景及项目星系材质/名称/轨道；列表与全屏星系同时保留，横排按钮已修复。新的星际 II 战术星图目前是研究建议，未替换进产品。旧的 186 项检查不构成当前美术验收。

模型身份、自动恢复、OS 内制作装卸、场景加载，以及本轮 228 项前端检查、45+2 项后端检查与恢复后构建见 [当前续接](OS_CAPABILITY_LIFECYCLE_CONTINUATION_20260906.md)。全部新原话、选择和否定关系见 [UR-278–UR-283](requirements/PAWOS_REQUIREMENTS_278_283.md)。本轮未安装或重启运行中的 Pi。
