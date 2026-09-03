# PAWOS 用户需求账本 · UR-223–UR-224

> 导航：[UR-221–UR-222](PAWOS_REQUIREMENTS_221_222.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-225](PAWOS_REQUIREMENTS_225_225.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

## User Requirement Ledger

### UR-223 — 同一运行终态通知只出现一次

- **状态 / 优先级：** `current / P0 notification correctness`
- **当前控制要求：** Session、Room、Trace 和 Memory 的同一次真实运行只能产生一条终态
  通知。轮询、刷新、窗口重开或同一终态重投影必须按稳定 session/run/event identity 幂等
  更新，不能不断追加“已结束运行”或相同超时失败。
- **不得：** 按标题或正文模糊去重；标题相同但 run identity 不同的真实新运行必须分别保留。
- **验收：** 同一终态重复投影仍为 1 条；下一次真实运行的终态新增第 2 条；Memory 失败通知
  保留一个明确重试/检查入口。
- **来源证据：** 用户粘贴的当前通知列表在 09:01、09:09、09:12 多次出现同名 Trace 终态，
  随后要求“并行改正”。列表文字是产品前台输出，不冒充用户创作的需求原话。

### UR-224 — Stop 必须终止真实回合并立即回落界面

- **状态 / 优先级：** `current / P0 Session cancellation`
- **当前控制要求：** 点击“停止本轮”后立即显示 `stopping`，Pi Runtime 取消当前 Provider、
  Tool、重试、压缩或子进程操作，并产生唯一终态；Composer 和状态栏在终态事件到达时立即
  回到可输入/非运行态。完整历史恢复是后续静默动作，不能决定 Stop 成功与否。
- **不得：** 用伪造 idle 掩盖仍在运行的任务、只隐藏 Stop 按钮、等待完整快照后才更新，或把
  “停止已接受但历史快照失败”显示成 Session 操作失败。
- **验收：** Stop 请求、Host cancel acknowledgement、terminal event、SQLite status 和前台
  状态使用同一 turn identity；终态即刻回落，随后刷新不复活旧 running。
- **来源原话：**

  > 因为停止也停止不了

## 继续阅读 / 编辑

- 下一份：[UR-225](PAWOS_REQUIREMENTS_225_225.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
