# PAWOS 用户需求账本 · UR-221–UR-222

> 导航：[UR-215–UR-220](PAWOS_REQUIREMENTS_215_220.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-223–UR-224](PAWOS_REQUIREMENTS_223_224.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

## User Requirement Ledger

### UR-221 — Trace 全自动模式自动继承目标项目绑定

- **状态 / 优先级：** `current / P0 Trace operability`
- **当前控制要求：** 从 Session、Room、Run 或 Memory 失败进入 Trace 时，只要来源对象
  已有权威 workspace/project binding，Trace 诊断与经用户授权的修复 Session 就自动继承
  同一绑定。全自动模式不能再次要求用户手填工作区，也不能用 `ENABLE_FULL_TRUST` 文案把
  已存在的项目上下文退回人工配置。
- **全自动能力：** 来源对象已选择 `full_trust` 时，Trace 的诊断 Skill 与后续 repair Session
  继承读取对话、读取已绑定外部文件和修改项目的能力，不重复逐 Tool 审批；仍必须把实际
  workspace、Session/run 与修改 diff 绑定到同一审计链。
- **安全边界：** 自动绑定只复用来源对象已经获准的根目录和能力；不得猜测目录、扩大写入
  范围或绕过 Trace 诊断到普通可写 Agent 的授权边界。来源确实没有绑定时，必须白话说明
  缺什么以及从哪里选择，而不是虚构项目。
- **验收：** 有绑定的来源一键 Trace 后，报告、修复候选和新验证均携带同一稳定项目身份；
  无绑定来源给出一个明确选择入口。
- **来源原话：**

  > 还有trace自动分配项目目录啊，全自动

  > `5c944447` · `2026-09-03T04:52:25.569Z` · “trace-agent-diagnostics在trace agnet 这个agetn是完整权限对吧，改项目和读对话无需同意，读外部文件也行，务必，因为这个需要自举就要能够改项目”

### UR-222 — Trace 结论必须先讲人话并明确可修复动作

- **状态 / 优先级：** `current / P0 diagnostic comprehension`
- **当前控制要求：** Trace 报告首屏按“发生了什么、对用户有什么影响、已经确认到哪一层、
  Trace 能自动修什么、下一步会做什么”说明。`session.settlement.get`、Provider、Runtime Host、
  request ID 等内部术语只能放在可展开证据详情里。
- **必须保留：** 根因置信度、证据边界、未确认项、修复授权和同案复验；白话化不能把候选
  根因冒充已确认，也不能把诊断冒充已经修复。
- **验收：** 不了解 PAW/Pi 内部架构的人无需读协议名就能决定“立即修复、查看证据或返回”；
  修复完成后显示改了什么以及新 Trace/Eval 是否通过。
- **来源原话：**

  > 当前诊断结果我看都看不懂

## Source coverage

- 当前消息对 Trace 自动绑定与可理解结果的要求分别映射到 `UR-221`、`UR-222`。
- 两张附件只作为当前前台可读性与缺少项目绑定的视觉证据，不从图片文字新增要求。
- 当前 Codex 文档环境未暴露稳定 message/turn ID；来源记录为当前任务、
  2026-09-01，不伪造。

## 继续阅读 / 编辑

- 下一份：[UR-223–UR-224](PAWOS_REQUIREMENTS_223_224.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
