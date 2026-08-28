# PAWOS 用户需求账本 · UR-188

> 导航：[UR-183–UR-187](PAWOS_REQUIREMENTS_183_187.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-189–UR-191](PAWOS_REQUIREMENTS_189_191.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

### UR-188 — Trace Agent 可从真实失败原因进入授权修复并复验

- **状态 / 优先级：** `current / P0 self-improvement loop`
- **真实需求：** Trace Agent 不只给笼统错误或只读报告。它应读取选中任务的
  真实 Trace/运行状态，展示失败阶段、原始可公开原因和未完成范围；诊断完成后
  提供明确的“交给 Agent 修复”动作，把诊断报告及相关证据交给普通可写 Agent
  Session。用户授权后该 Agent 可以改代码/配置，再用同一 Trace/Eval 范围复验。
- **边界：** Trace 诊断阶段保持只读，不能静默修改产品或数据；修复阶段使用
  普通 Agent 的权限和工具边界。失败报告不得把明确的 Runtime 原因降级成“读取
  或保存失败，请稍后重试”。
- 失败原因必须按权威来源分类展示：安全/审核策略拒绝、权限/审批、模型拒绝、参数或 Schema 验证、
  Tool 执行或非零退出、超时/取消、Runtime/网络、持久化以及资源不可用；来源没有公开细节时明确标为
  `unavailable` 并说明缺失边界，不能用笼统文案覆盖已有的真实原因。
- **首条真实案例：** 任务
  `memory-maintenance:<redacted-task-id>` 的真实原因是
  记忆整理内部 Session 仍有 active turn，37 天补齐任务在首日、0/37 处失败；
  修复和复验必须围绕该证据，不得误报为数据库写入失败。
- **原话依据：** “利用trace解决读取或保存失败，请稍后重试。任务
  memory-maintenance:<redacted-task-id>记忆一直失败”；
  “trace agent它能改正吗”。来源：当前任务，2026-08-28。

> 公开归档说明：任务标识已脱敏；失败阶段、影响范围、授权修复与复验语义保持不变。

## 继续阅读 / 编辑

- 下一份：[UR-189–UR-191](PAWOS_REQUIREMENTS_189_191.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
