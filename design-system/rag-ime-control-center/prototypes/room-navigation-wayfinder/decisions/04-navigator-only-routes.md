# 导航只决定归属

> 状态：closed
> 类型：domain decision

## Question

新需求进入 Project 后，Navigator 应该完成全部需求对齐，还是只把用户带到正确的 Room？

## Resolution

Navigator 是一次性路由器。它保存原始输入，只问到“继续哪个 Room、是否新建、是否改变当前航向、关联哪些旧 Room”足够清楚，然后退出。详细需求对齐由目标 Room 内的 `alignment-and-decision` 完成。

点击已知 Room 不调用 Navigator。模型建议的归属必须可见、可撤销；无法确定时先形成待归属需求，不静默创建 Room。

## Rejected alternatives

- 常驻导航聊天：积累无关上下文，并与 Room 形成第二个长期状态 owner。
- Navigator 完成详细 grilling：需求信息分散在项目入口与 Room 两处。
- 每个清晰子结果自动建多个 Room：用户需要同时管理过多上下文。

## Basis

- 用户选择“临时导航器”和“问到 Room 边界清楚就停止”。
- 当前技能流已经由 `alignment-and-decision` 负责 Room 内详细对齐，无需重复职责。

## Source refs

- `session-codex-project-field`
