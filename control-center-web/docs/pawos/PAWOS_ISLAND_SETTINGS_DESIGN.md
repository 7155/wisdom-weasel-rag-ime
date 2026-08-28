# PAWOS 岛屿与设置设计讨论稿

状态：`A-lite source prototype / not accepted / not foreground evidence`

本文只收敛 `UR-175` 的视觉与信息架构，不建立新的数据 owner，也不证明
前台已经交付。方向 A 的可逆第一阶段已有源码/聚焦测试原型；用户视觉确认前，
仍不能写成产品完成项。

## 已确认边界

- 岛屿是 PAWOS 的空间导航和美术隐喻，不自动等于一个 Project 或一个
  Room。
- 对话“文件”和项目“文件夹”只在 PAWOS 内显示，不写 Finder/Git，不复制
  transcript，也不成为第二权威。
- `Desktop / Wayfinder` 负责找项目与对话；`Agent` 持有 Session/Room；
  `Room` 是协作主工作面；`system-settings` 持有系统设置。
- Room 已有真实空间设置 owner。当前没有独立 `ProjectSettings` 对象；所谓
  “项目设置”只能先做现有权威的上下文入口或投影，不能制造另一份值。
- 岛屿探索不得挤占 Room 任务表，也不得阻塞 Trace/Eval 地基。

## 当前源码锚点

| 领域 | 当前 owner |
| --- | --- |
| 桌面与最近工作 | `PawDesktop.tsx`, `PawWayfinderWork.tsx` |
| PAWOS 虚拟项目文件夹 | `wayfinder-work-projection.ts` |
| Agent 内项目分组 | `PawAgentApp.tsx` |
| Room 任务表、协同模式、公开记录、星空 | `PawRoomWorkspace.tsx` |
| 每轮行星任务表 | `PawRoomRoundSheet.tsx` |
| 系统设置 | `PawSystemAppsMigrated.tsx` |
| 外观设置 | `PawOsAppearanceSettings.tsx` |
| 既有岛屿语言 | `features/project-field/index.tsx` |

## 2026-08-28 A-lite 源码原型

- 项目文件夹头部增加独立“项目上下文”入口；文件夹折叠后入口仍可使用，
  不把两个交互套在同一个 `summary` 中。
- Sheet 只读投影真实 workspace roots、Session / Room 数量、运行/需处理数量与
  当前对话；搜索后打开仍使用完整项目投影，不把搜索子集冒充项目全量。
- 对话入口继续打开 canonical Session / Room；快捷入口复用现有
  `system-settings:/configuration` 与 `system-monitor:/observability`。
- Sheet 支持返回、`Esc` 关闭与焦点返回。它不编辑字段，不新建
  `ProjectSettings`，不写 Finder/Git，也不复制 transcript。
- 聚焦投影/组件检查为 18/18，机械设计检测无发现。这些只是源码/测试边界；
  安装版、真实窗口尺寸和用户视觉接受仍未验证。

## 方向 A — 入口式岛屿 + 锚定设置 Sheet（推荐）

保留当前桌面与窗口模型，把“岛”作为清楚的入口和状态摘要，而不是新建
一个项目 Runtime。

```text
PAWOS 桌面
├─ 控制岛 ───────────────> System Settings（原 owner）
└─ 项目岛 / 项目文件夹
   ├─ 展开 Session / Room 对话文件
   ├─ 点击文件 ----------> 打开 canonical Session / Room
   └─ 上下文设置按钮 ----> 右侧锚定 Sheet
                            ├─ 当前 workspace roots（只读）
                            ├─ 常用 Session / Room 入口
                            ├─ Trace / Eval 快捷入口
                            └─ 跳转已有 Agent / Room / 系统设置
```

交互：

- 点击项目标题原地展开或折叠对话文件。
- 点击对话文件打开同一个真实对象。
- 点击项目岛上的设置按钮，从右侧打开 Sheet；宽窗并排，窄窗覆盖但保留
  明确返回。
- Room 内可提供同一个项目/空间入口，但 Sheet 不覆盖中央任务表，也不把
  Room 协同模式改名成项目模式。
- 当前内联非模态原型使用 `Esc`、返回按钮关闭，并把焦点返回原入口；
  它没有伪装成需要遮罩的模态对话框。

视觉：

- 岛按钮使用轻玻璃材质，只表达位置与状态。
- Sheet 使用偏纸面的内容材质，强调可读和可操作。
- 打开/关闭使用 180–240ms 的轻缩放、位移与模糊过渡；不做长距离飞行，
  不让装饰动画打断 Room 状态阅读。

第一阶段只聚合和跳转，不直接写入所谓“项目设置”。只有当一个字段已有
明确 schema、读取 owner 和保存 API 时，才允许在 Sheet 内原地编辑。

## 方向 B — 空间式岛屿 + Project Focus Mode

点击项目岛后进入完整项目聚焦空间：左侧是对话文件树，中央是当前
Session/Room，右侧是 workflow/引力与上下文设置；顶部控制岛负责回桌面和
系统设置。

这个方向空间感更强，但会同时改变桌面、窗口层、Project Field 与 Room
组合关系。它需要先回答“Project 是否成为可导航的一等对象”，否则容易把
视觉容器误写成新的业务 owner。因此不作为第一阶段实现。

## 推荐的第一阶段

先验证方向 A 的三件事：

1. 项目文件夹头部能否同时表达项目名、运行数、阻塞数和最近 Room，而不
   增加桌面噪声。
2. 控制岛能否清楚打开系统设置；项目岛能否清楚打开上下文 Sheet，且用户
   不会误以为两者保存两份设置。
3. Room 任务表保持视觉中心时，项目/空间入口和 workflow/引力入口是否仍
   容易找到。

第一阶段建议只做可运行的布局原型和真实对象投影，不添加 ProjectSettings
数据库、轮询器、同步层或装饰性假状态。

## 等待用户决定

- 控制岛只在桌面出现，还是在 Room 顶栏也保留一个小入口？
- 当前只读聚合/跳转原型通过视觉讨论后，下一阶段是继续保持入口式，还是
  允许直接编辑少量已有权威字段？
- workflow/引力默认在 Room 右侧，还是继续作为独立视图按钮？
- 星空保留独立入口，还是以后降成 Room / Project Focus 的背景层？
