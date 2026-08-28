# PAWOS 用户需求账本 · UR-182

> 导航：[UR-181](PAWOS_REQUIREMENTS_181_181.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-183–UR-187](PAWOS_REQUIREMENTS_183_187.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-182 — Room 行星窗口是紧凑只读观察面，卫星仅指行星 Session 内的 subagent

- **状态 / 优先级：** `current / P0 conversation surface`
- **术语：** Room participant 统一称为“行星”；只有某个行星对应的 Session
  内产生的 subagent 才称为“卫星”。Room participant 不是卫星。
- **真实需求：** 行星窗口是用于小窗观察的紧凑只读投影，不是完整 Session。
  在同样窗口面积内优先显示按权威顺序排列的消息、思考、工具、失败原因和运行
  状态；消息、思考、工具和失败直接采用高密度线性时间线，以状态点、缩进和细
  分隔线表达层级，不要逐条堆叠圆角卡片；保留必要的 Trace 与“打开完整 Session”
  导航入口。
- **视觉边界：** 行星观察窗不得添加厚重的装饰性外框、套框或大阴影卡片；只保留必要的
  标题栏、状态线和轻量分隔线，把有限面积留给真实时间线与失败/Trace 细节。
- **必须隐藏：** 行星窗口不显示底部发送框或 Composer，不显示模型名称/提供方、
  输入/输出/缓存/token、能力、权限等模型配置统计。完整 Session 的 Composer
  与干预能力只保留在用户明确打开的完整 Session 中。
- **交互边界：** 普通点击或导航打开行星仍能进入该行星的完整 Session 进行干预；
  行星观察窗自身不通过审批、发送、重试或其他写操作改变 Room/Session 状态。
  Room 主窗的 Composer 和治理/审批能力不受此要求影响。
- **禁止：** 不得通过全局删除主 Session Composer 来实现；Browser/Ego 不在本
  要求范围内；不得把行星 participant 与行星 Session 内 subagent 的窗口或术语
  混为一谈。
- **用户可见验收：** 给定包含多条消息、思考、工具和失败的真实投影，行星窗在
  首屏可见完整紧凑时间线及当前状态，无 Composer 或模型配置统计；Trace 与完整
  Session 入口可用；主 Agent/Room Session 仍保留原 Composer，卫星术语只用于
  行星 Session 的 subagent。
- **原话依据：** “room是弹出行星窗口”；“只有 subagent 才叫卫星”；
  “行星，是行星，不要这个发送框”；“gpt-5.6-sol openai-codex 输入 72.6K
  输出 87 缓存 99%行星也不要这些，是为了小窗口展示尽量多内容啊”；“而且
  行星不要框，是为了显示更多啊，不要加框”。来源：当前任务，2026-08-28。

## 继续阅读 / 编辑

- 下一份：[UR-183–UR-187](PAWOS_REQUIREMENTS_183_187.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
