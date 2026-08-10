# 聚焦不离开项目

> 状态：closed
> 类型：prototype decision

## Question

用户进入 Room 时，应该跳转到聊天页、弹出 Modal，还是在 Project Field 中改变观察分辨率？

## Resolution

Room 在原位置展开为 Room Workspace。镜头移动、信息密度提高，输入框进入 Room scope；其他 Room 降低密度但继续存在。退出时 Room 缩回原地，草稿与空间位置保留。

Project 打开只加载全部 Room 的低分辨率投影；聚焦后加载 Room Focus；完整历史和工具记录只在真正工作或检查时加载。

## Rejected alternatives

- 独立 Room 页面：切换上下文后整个项目消失。
- Modal：对象与空间位置断开，难以形成长期记忆。
- 一次加载所有 Room 完整聊天：破坏信息层级，也浪费 DOM 与模型上下文。

## Basis

- 用户接受“当前航程为默认视图，完整全景通过缩放进入”。
- 用户随后明确“去除，只要当前的”：不再提供独立全景切换，缩放本身承担空间总览。
- 用户进一步确认“没必要的部分可以去除”：单一视图下不再保留“当前航程”按钮，航线图例也不常驻。
- 当前原型已经验证 Room Focus、Escape 返回、Project 切换后恢复现场的基本交互。

## Source refs

- `doc-project-field-contract`
- `session-codex-project-field`
